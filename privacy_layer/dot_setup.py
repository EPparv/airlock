"""Configure the official OpenAI tunnel with scoped MCP access.

The tunnel identity and control-plane credential must be supplied by the owner.
No tunnel or external account credential is created by this program.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from .core import Gateway,EncryptedStore,Denied
from .sources import LocalSources
from .setup import ROOT,configure_dot
from .launcher import start

def main():
    start()
    sources=LocalSources();gateway=Gateway(EncryptedStore(ROOT/'.private/connections.enc',sources.key),sources)
    print('Use a tunnel associated with your ChatGPT workspace. The runtime key needs only Tunnels Read + Use.')
    identifier=input('OpenAI tunnel ID: ').strip()
    if not re.fullmatch(r'tunnel_[A-Za-z0-9]+',identifier):raise Denied('Invalid tunnel ID.')
    token=getpass.getpass('Airlock Dot connection token (hidden): ').strip()
    if gateway.authenticate(token)['agent']!='dot':raise Denied('Choose an approved Dot connection.')
    key=getpass.getpass('OpenAI tunnel runtime key (hidden): ').strip()
    if not key.startswith('sk-'):raise Denied('Enter an OpenAI runtime key, not your Venice key.')
    print(json.dumps(configure_dot(gateway,token,identifier,key)))
    print('Add this tunnel in ChatGPT → Plugins → Add custom MCP server → Tunnel. Only this Dot grant’s reviewed excerpts are available. Confirm the connection is Ready before testing.')

if __name__=='__main__':main()
