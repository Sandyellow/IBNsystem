"""
Mininet 拓扑 — 自动启动模式（无需手动 CLI 操作）
运行后等待 Ryu 控制器握手完成，再 pingAll 让 Ryu 发现所有主机，然后保持网络运行
"""
import time
import signal
import sys
import subprocess
import json
import os
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.topo import Topo
from mininet.log import setLogLevel, info
from mininet.link import TCLink

net = None  # 全局引用，供信号处理使用


def load_topology_config(config_path=None):
    """从配置文件加载拓扑，优先选用指定路径，其次尝试 topology.json"""
    if not config_path:
        import sys
        for i, arg in enumerate(sys.argv):
            if arg in ("--config", "-c") and i + 1 < len(sys.argv):
                config_path = sys.argv[i + 1]
                break
    
    if not config_path:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topology.json")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                info(f"[IBN] 成功加载拓扑配置文件: {config_path}\n")
                return json.load(f)
        except Exception as e:
            info(f"[IBN] 读取拓扑配置文件失败 ({config_path}): {e}，将采用默认配置。\n")
    return None


class IBNTopo(Topo):
    """树形拓扑: 支持从配置文件加载，或者 fallback 采用默认树形拓扑"""
    def build(self, config=None):
        if config:
            self._build_from_config(config)
        else:
            self._build_default()

    def _build_default(self):
        s1 = self.addSwitch("s1", cls=OVSKernelSwitch, protocols="OpenFlow13")
        s2 = self.addSwitch("s2", cls=OVSKernelSwitch, protocols="OpenFlow13")
        s3 = self.addSwitch("s3", cls=OVSKernelSwitch, protocols="OpenFlow13")

        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")
        h4 = self.addHost("h4", ip="10.0.0.4/24")

        bw = {"bw": 100, "delay": "1ms"}
        self.addLink(s1, s2, cls=TCLink, **bw)
        self.addLink(s1, s3, cls=TCLink, **bw)
        self.addLink(s2, h1, cls=TCLink, **bw)
        self.addLink(s2, h2, cls=TCLink, **bw)
        self.addLink(s3, h3, cls=TCLink, **bw)
        self.addLink(s3, h4, cls=TCLink, **bw)

    def _build_from_config(self, config):
        # 1. 添加交换机
        for sw in config.get("switches", []):
            self.addSwitch(sw["name"], cls=OVSKernelSwitch, protocols="OpenFlow13")
        
        # 2. 添加主机
        for host in config.get("hosts", []):
            self.addHost(host["name"], ip=host["ip"])
        
        # 3. 添加链路
        for link in config.get("links", []):
            bw_val = link.get("bw", 100)
            delay_val = link.get("delay", "1ms")
            bw = {"bw": bw_val, "delay": delay_val}
            self.addLink(link["src"], link["dst"], cls=TCLink, **bw)


def _wait_for_switches_connected(net, timeout=15):
    """
    轮询 ovs-vsctl show，等待所有交换机的 Controller 状态变为 is_connected: true。
    超时后打印警告并继续，不阻断启动流程。
    """
    switches = [sw.name for sw in net.switches]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = subprocess.check_output(
                ["ovs-vsctl", "show"], stderr=subprocess.DEVNULL, text=True
            )
            # 统计已连接的控制器数量
            connected = out.count("is_connected: true")
            if connected >= len(switches):
                info(f"[IBN] 所有 {len(switches)} 台交换机已连接到控制器。\n")
                return
        except Exception:
            pass
        time.sleep(0.5)
    info(f"[IBN] 警告：等待超时，部分交换机可能尚未连接到控制器，继续启动...\n")


def cleanup(sig=None, frame=None):
    global net
    if net:
        info("\n[IBN] 正在停止 Mininet...\n")
        net.stop()
    sys.exit(0)


def run(cli_mode=False):
    global net
    setLogLevel("info")

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    config = load_topology_config()
    topo = IBNTopo(config=config)
    net = Mininet(
        topo=topo,
        controller=RemoteController("c0", ip="127.0.0.1", port=6633),
        link=TCLink,
    )
    net.start()
    info("[IBN] Mininet 已启动: s1-s2-s3, h1-h4\n")
    info("[IBN] 主机 IP: h1=10.0.0.1  h2=10.0.0.2  h3=10.0.0.3  h4=10.0.0.4\n")

    # 等待所有 OVS 交换机与 Ryu 完成 OpenFlow 握手（CONNECTED 状态）
    info("[IBN] 等待交换机与控制器完成 OpenFlow 握手...\n")
    _wait_for_switches_connected(net, timeout=15)

    # 再等待 Ryu 完成初始流表下发（留 2 秒缓冲）
    time.sleep(2)

    # 自动 pingAll，让 Ryu 发现所有主机和链路（仅启动时执行一次）
    info("[IBN] 正在自动探测主机（pingAll）...\n")
    net.pingAll()
    info("[IBN] 拓扑探测完成。\n")

    if cli_mode:
        # 交互式 CLI 模式
        info("[IBN] 进入交互式 CLI 模式，输入 help 查看命令，exit 退出\n")
        from mininet.cli import CLI
        CLI(net)
        net.stop()
    else:
        # 后台守护模式：保持进程存活，不再周期 pingAll（避免拓扑抖动）
        info("[IBN] 网络运行中（后台模式）。按 Ctrl+C 停止。\n")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    import sys
    cli_mode = "--cli" in sys.argv
    run(cli_mode=cli_mode)
