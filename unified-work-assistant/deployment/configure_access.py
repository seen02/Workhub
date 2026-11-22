"""Set the Ubuntu host's HTTP entry point after initial data restore."""
import argparse,ipaddress,json,pathlib
root=pathlib.Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--listen',required=True,help='Server private IPv4 address, or 127.0.0.1 for host-only use')
a=parser.parse_args();ip=ipaddress.ip_address(a.listen)
if ip.version!=4 or not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
    raise SystemExit('Use the server private IPv4 address or 127.0.0.1.')
path=root/'compose.json';cfg=json.loads(path.read_text(encoding='utf-8'))
for name,service in cfg['services'].items():
    for port in service.get('ports',[]):
        port['host_ip']=str(ip) if name=='reverse-proxy' and int(port['published'])==80 else '127.0.0.1'
path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
print('HTTP 80 bind:',ip,'; other host ports remain loopback-only. Run manage.py start to apply.')
