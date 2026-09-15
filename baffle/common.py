#!/usr/bin/env python3
# Copyright 2026 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared constants and helpers used by both query.py and render.py."""

import base64
import glob
import os
import re
from urllib.parse import urlparse

# Bazel-logo-inspired greens, used throughout the generated site.
WAFFLE_DARK = '#12321f'
WAFFLE_DEEP = '#1b4d2e'
WAFFLE_BASE = '#2e7d32'
WAFFLE_MID = '#43a047'
WAFFLE_LIGHT = '#81c784'
WAFFLE_PALE = '#c8e6c9'
WAFFLE_MIST = '#e8f5e9'

ORGS = ['intrinsic-ai', 'intrinsic-opensource']

# The GitHub API only reveals org members who've made their membership
# public unless the querying token's own account is a member (see
# https://docs.github.com/en/rest/orgs/members). These usernames are known
# ros2/ament members whose membership is concealed from that check, so
# they're force-included regardless of what the live lookup returns.
ROS_MAINTAINER_OVERRIDES = [
    'asymingt',
    'cottsay',
    'kscottz',
    'sloretz',
    'tfoote',
    'wjwwood',
]

DATE_FILE_FORMAT = '%Y-%m-%d'
DATE_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.yaml$')
ANALYZED_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}_analyzed\.yaml$')

CLASSIFICATION_HUMAN = 'Human'
CLASSIFICATION_UNKNOWN = 'Unknown'
CLASSIFICATION_BOT = 'Bot'
CLASSIFICATION_AI = 'AI'
CLASSIFICATION_ORDER = [CLASSIFICATION_HUMAN, CLASSIFICATION_UNKNOWN, CLASSIFICATION_BOT, CLASSIFICATION_AI]

# Per-PR "Did you use Generative AI?" attestation, parsed from the PR
# template's response by analyze.py and rendered as an icon by render.py.
ATTESTATION_TICK = 'tick'
ATTESTATION_CROSS = 'cross'
ATTESTATION_WARNING = 'warning'

ATTESTATION_ICON = {
    ATTESTATION_TICK: '&#9989;',
    ATTESTATION_CROSS: '&#10060;',
    ATTESTATION_WARNING: '&#9888;&#65039;',
}
ATTESTATION_LABEL = {
    ATTESTATION_TICK: 'Generative AI use disclosed in the PR template',
    ATTESTATION_CROSS: 'PR template states no Generative AI was used',
    ATTESTATION_WARNING: 'Generative AI question missing or left blank',
}


def _find_latest(site_dir, pattern):
    candidates = [
        path for path in glob.glob(os.path.join(site_dir, '*.yaml'))
        if pattern.match(os.path.basename(path))
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.basename)


def find_latest_data_file(site_dir):
    cache_path = os.path.join(site_dir, 'issue_cache.yaml')
    if os.path.exists(cache_path):
        return cache_path
    return _find_latest(site_dir, DATE_FILE_RE)


def find_latest_analyzed_file(site_dir):
    cache_path = os.path.join(site_dir, 'issue_cache_analyzed.yaml')
    if os.path.exists(cache_path):
        return cache_path
    return _find_latest(site_dir, ANALYZED_FILE_RE)


def waffle_icon(size=48, cell_id='a', include_defs=True):
    """Return an inline SVG waffle icon (a green grid of waffle pockets)."""
    pad, cell, gap, cols = 10, 19, 8, 4
    cells = []
    for row in range(cols):
        for col in range(cols):
            x = pad + col * (cell + gap)
            y = pad + row * (cell + gap)
            cells.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="5" fill="url(#pocket-{cell_id})"/>')
            
    defs_block = f'''  <defs>
    <linearGradient id="body-{cell_id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{WAFFLE_MID}"/>
      <stop offset="100%" stop-color="{WAFFLE_BASE}"/>
    </linearGradient>
    <linearGradient id="pocket-{cell_id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{WAFFLE_DEEP}"/>
      <stop offset="100%" stop-color="{WAFFLE_DARK}"/>
    </linearGradient>
  </defs>''' if include_defs else ''

    return f'''<svg class="waffle-icon" width="{size}" height="{size}" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="waffle">
{defs_block}
  <rect x="3" y="3" width="114" height="114" rx="20" fill="url(#body-{cell_id})" stroke="{WAFFLE_DARK}" stroke-width="3"/>
  {''.join(cells)}
</svg>'''


def waffle_favicon_data_uri():
    svg = waffle_icon(size=64, cell_id='fav').replace('\n', '')
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'


def repo_from_url(url):
    parts = urlparse(url).path.strip('/').split('/')
    return '/'.join(parts[:2]) if len(parts) >= 2 else url
