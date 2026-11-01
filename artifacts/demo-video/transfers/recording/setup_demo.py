"""Prepare a separate local Mock environment without changing the existing demo."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[4]
config = json.loads(subprocess.check_output([
    'docker', 'compose', '-p', 'bava-bills-retake', '-f', 'docker-compose.yml',
    '-f', '/private/tmp/bava-bills-retake.override.yml', 'config', '--format', 'json'
], cwd=root))
config['name'] = 'bava-transfers-recording'
for service in config['services'].values():
    service.pop('build', None)
config['services']['postgres'].pop('ports', None)
config['services']['api']['ports'] = [{'target':8000,'published':'8001','host_ip':'127.0.0.1','protocol':'tcp'}]
config['services']['api']['environment']['API_PORT'] = '8000'
config['services']['api']['environment']['CORS_ORIGINS'] = '["http://localhost:3001"]'
config['services']['web']['ports'] = [{'target':3000,'published':'3001','host_ip':'127.0.0.1','protocol':'tcp'}]
config['services']['web']['image'] = 'bava-recording-web:local'
config['services']['web']['environment']['NEXT_PUBLIC_API_BASE_URL'] = 'http://localhost:8001'
config['volumes'] = {'postgres-data': {'name':'bava-transfers-recording-postgres-data'}}
for network in config.get('networks', {}).values():
    network.pop('name',None)
path = Path('/private/tmp/bava-transfers-recording.json')
path.write_text(json.dumps(config))
os.chmod(path,0o600)
build_context = Path('/private/tmp/bava-recording-web-build')
build_context.mkdir(exist_ok=True)
dockerfile = build_context / 'Dockerfile'
dockerfile.write_text('FROM banking-agent-web:latest\n'
    'RUN find /app/apps/web/.next -type f -name "*.js" -exec sed -i "s|http://localhost:8000|http://localhost:8001|g" {} +\n')
# Reuse the already built local app; only bind its public API URL to the isolated port.
subprocess.run(['docker','build','--pull=false','-t','bava-recording-web:local',str(build_context)],cwd=root,check=True)
subprocess.run(['docker','compose','-p','bava-transfers-recording','-f',str(path),'up','-d'],cwd=root,check=True)
