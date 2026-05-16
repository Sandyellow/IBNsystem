"""
Mininet 拓扑 — 自动启动模式（无需手动 CLI 操作）
运行后自动 pingAll 让 Ryu 发现所有主机，然后保持网络运行
"""
import time
import signal
import sys
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.topo import Topo
from mininet.log import setLogLevel, info
from mininet.link import TCLink

net = None  # 全局引用，供信号处理使用


class IBNTopo(Topo):
    """树形拓扑: s1 为核心，s2/s3 为边缘，h1-h4 为主机"""
    def build(self):
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

    topo = IBNTopo()
    net = Mininet(
        topo=topo,
        controller=RemoteController("c0", ip="127.0.0.1", port=6633),
        link=TCLink,
    )
    net.start()
    info("[IBN] Mininet 已启动: s1-s2-s3, h1-h4\n")
    info("[IBN] 主机 IP: h1=10.0.0.1  h2=10.0.0.2  h3=10.0.0.3  h4=10.0.0.4\n")

    # 自动 pingAll，让 Ryu 发现所有主机和链路
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
        # 后台守护模式
        info("[IBN] 网络运行中（后台模式）。按 Ctrl+C 停止。\n")
        while True:
            time.sleep(30)
            net.pingAll()


if __name__ == "__main__":
    import sys
    cli_mode = "--cli" in sys.argv
    run(cli_mode=cli_mode)
