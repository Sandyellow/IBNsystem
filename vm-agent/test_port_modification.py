import requests
RYU_BASE = "http://127.0.0.1:8080"

def modify_port():
    body = {
        "dpid": 1,
        "port_no": 1,
        "config": 1,
        "mask": 1
    }
    r = requests.post(f"{RYU_BASE}/stats/portdesc/modify", json=body)
    print(r.status_code)
    print(r.text)

if __name__ == "__main__":
    modify_port()
