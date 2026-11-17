"""Operator-only committed image build with a temporary host-DNS BuildKit."""
import ipaddress
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
from dev import ROOT, require_local_docker
import image

BUILDKIT = 'moby/buildkit:buildx-stable-1@sha256:c5f8862f52499773af85bc07695b2379ef08e8002352b0df2c4864c91d78dabe'


def build():
    require_local_docker()
    revision, payload, context = image.committed_context()
    reference = 'accounting-platform:' + revision
    if image.inspect(reference) is not None:
        return image.reuse_for_verification(reference)
    resolver = Path('/etc/resolv.conf').read_text()
    servers = []
    for line in resolver.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == 'nameserver':
            value = str(ipaddress.ip_address(parts[1]))
            if value not in servers:servers.append(value)
    if not servers:raise RuntimeError('Δεν βρέθηκε nameserver στον υπολογιστή.')
    python_image = json.loads((ROOT/'docker/image-pins.json').read_text())['python']['reference']
    if not (ROOT/'Dockerfile').read_text().startswith('FROM ' + python_image + '\n'):
        raise RuntimeError('Η βασική εικόνα διαφέρει από την καταγεγραμμένη.')
    builder = 'accounting-s27-dns-' + secrets.token_hex(8)
    node = builder + '0'
    container = 'buildx_buildkit_' + node
    if subprocess.run(['docker','buildx','inspect',builder],capture_output=True).returncode == 0:
        raise RuntimeError('Υπάρχει ήδη ο προσωρινός builder.')
    if subprocess.run(['docker','container','inspect',container],capture_output=True).returncode == 0:
        raise RuntimeError('Υπάρχει ήδη το προσωρινό container.')
    def run(args, **kwargs):return subprocess.run(args,check=True,**kwargs)
    with tempfile.TemporaryDirectory(prefix='accounting-s27-dns-') as directory:
        config = Path(directory)/'buildkitd.toml'
        config.write_text('[dns]\n  nameservers = ' + json.dumps(servers) +
            '\n  options = ["timeout:2", "attempts:2"]\n\n[worker.oci]\n  networkMode = "host"\n')
        owned = False
        try:
            print('[S27] Προσωρινός builder με resolver υπολογιστή: ' + ', '.join(servers),flush=True)
            run(['docker','buildx','create','--name',builder,'--node',node,'--driver','docker-container',
                '--driver-opt','network=host','--driver-opt','restart-policy=no','--driver-opt','image='+BUILDKIT,
                '--buildkitd-config',str(config),'--buildkitd-flags','--allow-insecure-entitlement network.host'])
            owned = True
            run(['docker','buildx','inspect','--bootstrap',builder])
            metadata = json.loads(subprocess.check_output(['docker','container','inspect',container],text=True))[0]
            private_resolver = Path(metadata.get('ResolvConfPath',''))
            if (metadata.get('Name') != '/'+container or metadata.get('HostConfig',{}).get('NetworkMode') != 'host'
                    or private_resolver.name != 'resolv.conf' or private_resolver.parent.name != metadata['Id']):
                raise RuntimeError('Ο νέος builder ή το ιδιωτικό resolv.conf δεν συμφωνεί.')
            run(['docker','exec','-i','--user','0',container,'sh','-c','cat > /etc/resolv.conf'],input=resolver.encode())
            common = ['docker','buildx','build','--builder',builder,'--network','host','--allow','network.host',
                '--platform','linux/amd64','--progress','plain']
            proof = '''import socket, urllib.request
for host in ("deb.debian.org", "pypi.org", "files.pythonhosted.org"):
    socket.getaddrinfo(host, 443)
    print(host + ": DNS OK", flush=True)
for url in ("http://deb.debian.org/debian/dists/bookworm/InRelease", "https://pypi.org/simple/amqp/"):
    with urllib.request.urlopen(url, timeout=12) as response:
        assert response.status == 200
        print(url + ": HTTP OK", flush=True)
'''
            dockerfile = ('FROM '+python_image+'\nRUN '+json.dumps(['python','-c',proof])+'\n').encode()
            run(common+['--output','type=cacheonly','-'],input=dockerfile,cwd=ROOT)
            run(common+['--load','--pull','--file','Dockerfile','--build-arg','APP_REVISION='+revision,
                '--label','gr.accounting.source-context='+context['digest'],'--tag',reference,'-'],input=payload,cwd=ROOT)
        finally:
            if owned:
                cleanup = subprocess.run(['docker','buildx','rm','--force',builder])
                if cleanup.returncode:raise RuntimeError('Χρειάζεται καθαρισμός μόνο του προσωρινού builder: '+builder)
    return image.reuse_for_verification(reference)
