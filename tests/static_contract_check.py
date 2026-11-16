#!/usr/bin/env python3
"""Offline syntax and layout verification. No ROS, network, robot or file mutation."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SHELLS = ['01_setup_env.sh', '02_create_map.sh', '03_run_nav.sh', 'setup_maps.sh', 'scripts/_env.sh']
PYTHON = ['scripts/environment.py', 'scripts/map_catalog.py',
          'scripts/map_preview_capture.py', 'map_manager.py',
          'tests/test_map_manager.py']
HTML = ['slam_nav2_tutorial.html', 'map_manager.html']


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        identifier = attributes.get('id')
        if identifier:
            if identifier in self.ids:
                self.duplicates.append(identifier)
            self.ids.add(identifier)
        if attributes.get('href', '').startswith('#'):
            self.links.append(attributes['href'][1:])


def main():
    actual_shells = {p.name for p in ROOT.glob('*.sh')}
    expected_shells = set(SHELLS[:-1])
    assert actual_shells == expected_shells, f'root entrypoints: {actual_shells} != {expected_shells}'
    for file in SHELLS:
        result = subprocess.run(['bash', '-n', str(ROOT / file)], capture_output=True, text=True)
        assert result.returncode == 0, f'bash -n {file}: {result.stderr}'
    mapping = (ROOT / '02_create_map.sh').read_text(encoding='utf-8')
    navigation = (ROOT / '03_run_nav.sh').read_text(encoding='utf-8')
    assert 'map_$(date +%Y%m%d_%H%M%S)_$/rtabmap.db' in mapping, 'missing mapping PID'
    assert mapping.count('$pointer.$.tmp') == 2, 'non-unique pointer temp file'
    assert 'restart_map:=false' in mapping and 'restart_map:=false' in navigation
    assert 'ENABLE_MOTION=false' in navigation and 'if [[ "$MODE" == drive ]]; then ENABLE_MOTION=true; fi' in navigation
    assert 'cp -p -- "$DB" "$SESSION_DB"' in navigation, 'navigation must copy original map'
    helper = (ROOT / 'scripts/_env.sh').read_text(encoding='utf-8')
    assert 'go2_auto_network_interface()' in helper, 'missing Go2 wired-network selection'
    assert 'conda activate go2_nav2' in helper, 'missing environment auto activation'
    assert 'iface=lo' not in helper, 'unsafe loopback fallback'
    for file in PYTHON:
        ast.parse((ROOT / file).read_text(encoding='utf-8'), filename=file)
    for file in HTML:
        content = (ROOT / file).read_text(encoding='utf-8')
        parser = Structure()
        parser.feed(content)
        assert not parser.duplicates, f'{file}: duplicated ids {parser.duplicates}'
        assert all(anchor in parser.ids for anchor in parser.links), f'{file}: broken local anchors'
        if file == 'slam_nav2_tutorial.html':
            for shell in SHELLS[:3]:
                assert f'bash ./{shell}' in content
            assert 'docs/images/go2-edu-hero.png' in content
            assert 'docs/KakaoTalk_20261112_203846672_web.mp4' in content
            assert 'map_manager.html' not in content and 'map_manager.py' not in content
            assert 'Map Manager' not in content, 'tutorial must not mention administrator app'
            assert 'class="media-results"' in content, 'video and results must be adjacent'
            assert '.steps>li>div{display:block' in content, 'Ctrl+C keyboard tokens must wrap inline'
            assert 'bash ./03_run_nav.sh</code>' in content, 'safe default command missing'
            assert 'bash ./03_run_nav.sh drive' in content, 'operator motion must be explicit'
            for disallowed in ('SSH', '초보자', 'read -r -p', 'GO2_NET_IFACE', 'CYCLONEDDS_URI',
                               '성공한 실행에서 해당하는', 'nav.rviz'):
                assert disallowed not in content, f'tutorial contains obsolete discussion: {disallowed}'
        else:
            assert '03_run_nav.sh' not in content and 'slam_nav2_tutorial.html' not in content
    print('PASS: shell syntax, Python AST, HTML anchors, root scripts and UI separation')
    print('NOT TESTED: Conda installation, ROS topic reception, GUI, Mapping, Nav2 and physical Go2 motion')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, SyntaxError, OSError, ValueError) as error:
        print('FAIL:', error, file=sys.stderr)
        raise SystemExit(1)
