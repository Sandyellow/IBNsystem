"""
Ryu 控制器 — IBN 系统 SDN 控制平面
特性:
1. L2 自学习转发 (Priority=10)
2. ARP 代答 (ARP Proxy) - 消除泛洪广播风暴
3. 防环生成树 (Spanning Tree) - 基于拓扑计算阻断冗余链路
4. OpenFlow 1.3
"""
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp
from ryu.topology import event as topo_event


class IBNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}      # dpid -> {mac -> port}
        self.arp_table = {}        # ip -> mac 全局 ARP 代理表
        
        # 拓扑感知与生成树状态
        self.switches = {}         # dpid -> Datapath
        self.links = []            # 全局链路
        self.spanning_tree_installed = False

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """交换机握手：安装 table-miss 流表，将未知包送控制器"""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        # Table-miss priority = 0
        self._add_flow(datapath, 0, match, actions)
        self.logger.info("Switch connected: dpid=%s", datapath.id)

    def _add_flow(self, datapath, priority, match, actions, idle=0, hard=0):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst    = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod     = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=inst, idle_timeout=idle, hard_timeout=hard,
        )
        datapath.send_msg(mod)

    # ── 拓扑感知与生成树 (STP) 防环 ────────────────────────────────
    
    @set_ev_cls(topo_event.EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        sw = ev.switch
        self.switches[sw.dp.id] = sw.dp
        self.logger.info("Topology: switch entered dpid=%s", sw.dp.id)

    @set_ev_cls(topo_event.EventLinkAdd)
    def _link_add_handler(self, ev):
        link = ev.link
        # 防止重复添加
        if link not in self.links:
            self.links.append(link)
            self.logger.info("Topology: link added %s:%s -> %s:%s",
                             link.src.dpid, link.src.port_no,
                             link.dst.dpid, link.dst.port_no)
            # 每次有新链路时，触发防环计算
            if len(self.switches) >= 2:
                self._install_spanning_tree()

    def _install_spanning_tree(self):
        """基于已知拓扑计算生成树，阻塞冗余链路，防止广播风暴"""
        dpids = list(self.switches.keys())
        if len(dpids) < 2:
            return

        adj = {d: [] for d in dpids}
        for link in self.links:
            s, d = link.src.dpid, link.dst.dpid
            adj.setdefault(s, []).append((d, link.src.port_no))
            adj.setdefault(d, []).append((s, link.dst.port_no))

        visited = set()
        tree_edges = set()
        blocked = []

        root = dpids[0]
        queue = [root]
        visited.add(root)

        # BFS 构建生成树
        while queue:
            cur = queue.pop(0)
            for neighbor, port in adj.get(cur, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    tree_edges.add((cur, neighbor))
                    tree_edges.add((neighbor, cur))

        # 找出非树边，准备阻塞
        for link in self.links:
            s, d = link.src.dpid, link.dst.dpid
            if (s, d) not in tree_edges:
                blocked.append((s, link.src.port_no, d))
                blocked.append((d, link.dst.port_no, s))

        for dpid, port, peer in blocked:
            dp = self.switches.get(dpid)
            if dp is None:
                continue
            parser = dp.ofproto_parser
            match = parser.OFPMatch(in_port=port)
            actions = []  # Empty actions = DROP
            # 使用 priority=20 阻塞冗余链路（高于基础转发 10，低于业务策略 400）
            self._add_flow(dp, 20, match, actions)
            self.logger.info("STP: blocked port %s on s%s (link to s%s)", port, dpid, peer)

        self.spanning_tree_installed = True

    # ── ARP 代答与自学习转发 ───────────────────────────────────────

    def _handle_arp(self, datapath, in_port, pkt_ethernet, pkt_arp):
        """拦截 ARP 并代答，避免泛洪"""
        if pkt_arp.opcode != arp.ARP_REQUEST:
            return False

        src_mac = pkt_arp.src_mac
        src_ip = pkt_arp.src_ip
        dst_ip = pkt_arp.dst_ip
        dpid = datapath.id
        parser = datapath.ofproto_parser

        # 记录发送者的 IP -> MAC
        self.arp_table[src_ip] = src_mac

        # 如果控制器知道目标 MAC，则直接代答
        if dst_ip in self.arp_table:
            dst_mac = self.arp_table[dst_ip]
            self.logger.info("ARP Proxy: replying %s is at %s to %s", dst_ip, dst_mac, src_ip)
            
            # 伪造 ARP Reply 报文
            e = ethernet.ethernet(dst=src_mac, src=dst_mac, ethertype=ethernet.eth.ethertype)
            a = arp.arp(hwtype=1, proto=0x0800, hlen=6, plen=4, opcode=arp.ARP_REPLY,
                        src_mac=dst_mac, src_ip=dst_ip,
                        dst_mac=src_mac, dst_ip=src_ip)
            p = packet.Packet()
            p.add_protocol(e)
            p.add_protocol(a)
            p.serialize()

            # 将响应从原端口发回
            actions = [parser.OFPActionOutput(in_port)]
            out = parser.OFPPacketOut(
                datapath=datapath, buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                in_port=datapath.ofproto.OFPP_CONTROLLER,
                actions=actions, data=p.data)
            datapath.send_msg(out)
            return True # 已处理
        return False

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """L2 自学习转发（带异常防护与健壮校验）"""
        try:
            msg      = ev.msg
            datapath = msg.datapath
            ofproto  = datapath.ofproto
            parser   = datapath.ofproto_parser
            in_port  = msg.match["in_port"]
            dpid     = datapath.id

            pkt = packet.Packet(msg.data)
            eth_list = pkt.get_protocols(ethernet.ethernet)
            if not eth_list:
                return
            eth = eth_list[0]
            dst, src = eth.dst, eth.src

            # 核心防护：丢弃 LLDP 包，防止自学习交换机将其泛洪导致 rest_topology 产生幽灵链路
            if eth.ethertype == 0x88cc:
                return
                
            # 丢弃 IPv6 报文，防止产生不必要的泛洪风暴
            if eth.ethertype == 0x86dd:
                return

            # ARP Proxy 拦截处理
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                # 尝试代答。如果代答成功，就不继续走后续的泛洪转发了
                if self._handle_arp(datapath, in_port, eth, arp_pkt):
                    return
                # 否则继续走到后面去泛洪寻找未知的 IP

            # 如果不是 ARP，或者是未知的 ARP，则继续 L2 学习逻辑
            self.mac_to_port.setdefault(dpid, {})
            self.mac_to_port[dpid][src] = in_port

            out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
            actions  = [parser.OFPActionOutput(out_port)]

            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
                # 使用 priority=10 作为底层 L2 转发，留出高优先级空间给业务策略 (400-500)
                self._add_flow(datapath, 10, match, actions, idle=60)

            data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            out  = parser.OFPPacketOut(
                datapath=datapath, buffer_id=msg.buffer_id,
                in_port=in_port, actions=actions, data=data,
            )
            datapath.send_msg(out)
        except Exception as e:
            self.logger.error("Error handling packet_in: %s", str(e), exc_info=True)

