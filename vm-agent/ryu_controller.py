"""
Ryu 控制器 — IBN 系统 SDN 控制平面
L2 自学习转发 + OpenFlow 1.3
注意：拓扑发现由 ryu.topology.switches 独立加载，不在此冲突声明
"""
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet


class IBNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}      # dpid -> {mac -> port}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """交换机握手：安装 table-miss 流表，将未知包送控制器"""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
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
                self.logger.warning("Received packet without Ethernet header from dpid=%s", dpid)
                return
            eth = eth_list[0]
            dst, src = eth.dst, eth.src

            # 核心修复：丢弃 LLDP 包，防止 L2 自学习交换机将其泛洪导致 rest_topology 产生幽灵链路
            if eth.ethertype == 0x88cc:
                return
                
            # 丢弃 IPv6 的多播/邻居发现包，防止产生不必要的泛洪风暴
            if eth.ethertype == 0x86dd:
                return

            self.mac_to_port.setdefault(dpid, {})
            self.mac_to_port[dpid][src] = in_port

            out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
            actions  = [parser.OFPActionOutput(out_port)]

            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
                self._add_flow(datapath, 1, match, actions, idle=30)

            data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            out  = parser.OFPPacketOut(
                datapath=datapath, buffer_id=msg.buffer_id,
                in_port=in_port, actions=actions, data=data,
            )
            datapath.send_msg(out)
        except Exception as e:
            self.logger.error("Error handling packet_in: %s", str(e), exc_info=True)
