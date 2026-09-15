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

"""VIEW stage: renders the most recent "<date>_analyzed.yaml" file (the
CONTROLLER stage's output) into a static HTML waffle board (site/index.html),
grouped into Human / Unknown / Bot / AI tables in that order so
human-authored PRs are prioritized."""

import datetime
import html
import os
import subprocess
import sys

import yaml

from common import ATTESTATION_ICON
from common import ATTESTATION_LABEL
from common import ATTESTATION_WARNING
from common import CLASSIFICATION_AI
from common import CLASSIFICATION_BOT
from common import CLASSIFICATION_HUMAN
from common import CLASSIFICATION_ORDER
from common import CLASSIFICATION_UNKNOWN
from common import WAFFLE_BASE
from common import WAFFLE_DARK
from common import WAFFLE_DEEP
from common import WAFFLE_LIGHT
from common import WAFFLE_MID
from common import WAFFLE_MIST
from common import WAFFLE_PALE
from common import find_latest_analyzed_file
from common import waffle_favicon_data_uri
from common import waffle_icon

GROUP_ICON = {
    CLASSIFICATION_HUMAN: '&#129489;',   # person
    CLASSIFICATION_UNKNOWN: '&#10067;',  # question mark
    CLASSIFICATION_BOT: '&#129302;',     # robot
    CLASSIFICATION_AI: '&#129504;',      # brain
}


def detect_repo_url():
    # Check GitHub Actions env var
    repo = os.environ.get('GITHUB_REPOSITORY')
    if repo:
        return f"https://github.com/{repo}"

    # Fallback: check git config
    try:
        url = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url'], text=True).strip()
        if url.startswith('git@github.com:'):
            url = url.replace('git@github.com:', 'https://github.com/').replace('.git', '')
        elif url.endswith('.git'):
            url = url[:-4]
        return url
    except Exception:
        return "https://github.com/intrinsic-opensource/intrinsic-triage"


def parse_iso(value):
    return datetime.datetime.fromisoformat(value)


def format_age(days):
    years, remainder_days = divmod(days, 365)
    if years >= 1:
        return '%d yr%s' % (years, '' if years == 1 else 's')
    return '%d day%s' % (remainder_days, '' if remainder_days == 1 else 's')


def render_row(row, users, icon_sm, row_number):
    author = row['author']
    user = users.get(author, {})
    author_url = 'https://github.com/' + author
    is_maintainer = user.get('is_ros_maintainer', False)
    maintainer_badge = ' <span class="maintainer-badge" title="ROS maintainer">&#9733;</span>' if is_maintainer else ''
    tooltip_parts = []
    if user.get('account_age_days'):
        tooltip_parts.append('Account age: %s' % format_age(user['account_age_days']))
    if user.get('open_pr_count') is not None:
        # Search-restricted account: the public_* counts are all zero
        # placeholders, so show the burst inputs that drove the call instead.
        tooltip_parts.append('Public history hidden by GitHub')
        tooltip_parts.append('Open ROS PRs: %d (peak %d/hr)' % (
            user['open_pr_count'], user.get('max_pr_burst', 0)))
    else:
        if user.get('public_pull_requests') is not None:
            tooltip_parts.append('Public PRs: %d' % user['public_pull_requests'])
        if user.get('public_issues') is not None:
            tooltip_parts.append('Public issues: %d' % user['public_issues'])
        if user.get('public_reviews') is not None:
            tooltip_parts.append('Public reviews: %d' % user['public_reviews'])
    tooltip = html.escape(' · '.join(tooltip_parts))
    attestation = row.get('ai_attestation', ATTESTATION_WARNING)
    attestation_icon = ATTESTATION_ICON[attestation]
    attestation_label = html.escape(ATTESTATION_LABEL[attestation])
    pr_number = row['url'].split('/')[-1]
    body_escaped = html.escape(row.get('body', ''))
    title_escaped = html.escape(row['title'])
    return f'''      <tr data-updated="{html.escape(row['updated'])}" data-title="{title_escaped}" data-body="{body_escaped}">
        <td class="col-num">{row_number}</td>
        <td class="col-repo"><span class="pill">{html.escape(row['repo'])}#{pr_number}</span></td>
        <td class="col-title"><a href="{html.escape(row['url'])}" target="_blank" rel="noopener">{html.escape(row['title'])}</a></td>
        <td class="col-author" title="{tooltip}"><a href="{html.escape(author_url)}" target="_blank" rel="noopener">@{html.escape(author)}</a>{maintainer_badge}</td>
        <td class="col-ai" title="{attestation_label}">{attestation_icon}</td>
        <td class="col-updated">{parse_iso(row['updated']).strftime('%b %d, %Y')}</td>
        <td class="col-icon"><div class="waffle-container">{icon_sm}<input type="checkbox" data-url="{html.escape(row['url'])}"></div></td>
      </tr>'''


def render_group(classification, rows, users, icon_sm, start_index):
    if not rows:
        return ''
    body_rows = [render_row(row, users, icon_sm, start_index + idx) for idx, row in enumerate(rows)]
    return f'''    <section class="group">
      <h2 class="group-heading">{GROUP_ICON[classification]} {html.escape(classification)} <span class="count-badge">{len(rows)}</span></h2>
      <table>
        <thead>
          <tr>
            <th class="col-num">#</th>
            <th class="col-repo">Repository</th>
            <th class="col-title">Title</th>
            <th class="col-author">Author</th>
            <th class="col-ai">AI</th>
            <th class="col-updated">Last updated</th>
            <th class="col-icon"></th>
          </tr>
        </thead>
        <tbody>
          <tr class="empty-fortnight-row" style="display: none;">
            <td colspan="7" style="text-align: center; padding: 2rem; color: var(--waffle-base); font-style: italic;">
              No PRs were found for the last fortnight. Use the links below to pull up older issues.
            </td>
          </tr>
{chr(10).join(body_rows)}
        </tbody>
      </table>
    </section>'''


def render_html(data, generated_at):
    rows = data.get('pull_requests', [])
    users = data.get('users', {})
    repo_url = detect_repo_url()
    icon_lg = waffle_icon(size=64, cell_id='hero', include_defs=False)
    icon_sm = waffle_icon(size=28, cell_id='row', include_defs=False)
    favicon = waffle_favicon_data_uri()

    grouped = {classification: [] for classification in CLASSIFICATION_ORDER}
    for row in rows:
        classification = users.get(row['author'], {}).get('classification', CLASSIFICATION_UNKNOWN)
        grouped.setdefault(classification, []).append(row)

    if rows:
        sections = []
        current_index = 1
        for classification in CLASSIFICATION_ORDER:
            group_rows = grouped.get(classification, [])
            if not group_rows:
                continue
            sections.append(render_group(classification, group_rows, users, icon_sm, current_index))
            current_index += len(group_rows)
        sections_html = '\n'.join(sections)
        badge_text = ' · '.join(
            '%d %s' % (len(grouped.get(classification, [])), classification)
            for classification in CLASSIFICATION_ORDER
        )
    else:
        sections_html = f'''    <div class="empty-plate">
      {icon_lg}
      <p>No waffles today &mdash; the plate is clean!</p>
    </div>'''
        badge_text = '0 open on the plate'

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Baffle Board</title>
<link rel="icon" href="{favicon}">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {{
    --waffle-dark: {WAFFLE_DARK};
    --waffle-deep: {WAFFLE_DEEP};
    --waffle-base: {WAFFLE_BASE};
    --waffle-mid: {WAFFLE_MID};
    --waffle-light: {WAFFLE_LIGHT};
    --waffle-pale: {WAFFLE_PALE};
    --waffle-mist: {WAFFLE_MIST};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background:
      radial-gradient(circle at 8px 8px, var(--waffle-pale) 2px, transparent 2px) 0 0 / 32px 32px,
      var(--waffle-mist);
    color: var(--waffle-dark);
    min-height: 100vh;
  }}
  .hero {{
    background: linear-gradient(135deg, var(--waffle-deep), var(--waffle-base) 55%, var(--waffle-mid));
    color: var(--waffle-mist);
    padding: 2.5rem 1.5rem 3rem;
    text-align: center;
    box-shadow: 0 6px 18px rgba(18, 50, 31, 0.35);
  }}
  .hero-icons {{
    display: flex;
    justify-content: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }}
  .hero-icons .waffle-icon {{ filter: drop-shadow(0 3px 4px rgba(0,0,0,0.25)); }}
  .hero h1 {{
    margin: 0 0 0.35rem;
    font-size: 2.25rem;
    letter-spacing: 0.02em;
  }}
  .hero p {{
    margin: 0.25rem 0;
    opacity: 0.9;
  }}
  .badge {{
    display: inline-block;
    margin-top: 0.75rem;
    padding: 0.35rem 0.9rem;
    background: rgba(232, 245, 233, 0.15);
    border: 1px solid rgba(232, 245, 233, 0.4);
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.9rem;
  }}
  .repo-link {{
    display: inline-block;
    margin-top: 0.5rem;
    margin-bottom: 0.5rem;
    color: var(--waffle-pale);
    transition: color 0.15s ease, transform 0.15s ease;
  }}
  .repo-link:hover {{
    color: white;
    transform: scale(1.08);
  }}
  main {{
    max-width: 1400px;
    margin: -1.75rem auto 3rem;
    padding: 0 1.5rem;
  }}
  .group {{
    background: white;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(18, 50, 31, 0.18);
    overflow: hidden;
    border: 1px solid var(--waffle-pale);
    margin-bottom: 1.5rem;
  }}
  .group-heading {{
    margin: 0;
    padding: 1rem 1.25rem;
    background: var(--waffle-deep);
    color: var(--waffle-mist);
    font-size: 1.1rem;
  }}
  .count-badge {{
    display: inline-block;
    background: rgba(232, 245, 233, 0.2);
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-size: 0.85rem;
    margin-left: 0.4rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.95rem;
  }}
  thead th {{
    text-align: left;
    background: var(--waffle-mist);
    color: var(--waffle-deep);
    padding: 0.85rem 1rem;
    border-bottom: 2px solid var(--waffle-light);
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.06em;
  }}
  tbody tr {{
    border-bottom: 1px solid var(--waffle-mist);
    transition: background 0.15s ease;
  }}
  tbody tr:nth-child(even) {{ background: var(--waffle-mist); }}
  tbody tr:hover {{ background: var(--waffle-pale); }}
  td {{ padding: 0.65rem 1rem; vertical-align: middle; }}
  .col-num {{ width: 30px; color: #5a6b5f; font-size: 0.85rem; }}
  .col-icon {{ width: 44px; }}
  .waffle-container {{
    position: relative;
    display: inline-block;
    width: 28px;
    height: 28px;
    vertical-align: middle;
  }}
  .waffle-container input[type="checkbox"] {{
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    margin: 0;
    cursor: pointer;
  }}
  .pill {{
    display: inline-block;
    background: var(--waffle-pale);
    color: var(--waffle-deep);
    border-radius: 999px;
    padding: 0.2rem 0.7rem;
    font-size: 0.8rem;
    font-weight: 600;
    white-space: nowrap;
  }}

  .col-title a {{
    color: var(--waffle-base);
    text-decoration: none;
    font-weight: 600;
  }}
  .col-title a:hover {{ text-decoration: underline; }}
  .col-repo {{ width: 280px; }}
  .col-author {{ width: 180px; }}
  .col-author a {{
    color: var(--waffle-deep);
    text-decoration: none;
    white-space: nowrap;
  }}
  .col-author a:hover {{ text-decoration: underline; }}
  .maintainer-badge {{ color: #f9a825; cursor: default; }}
  .col-ai {{ width: 60px; text-align: center; font-size: 1.1rem; cursor: default; }}
  .col-updated {{ width: 140px; color: #5a6b5f; white-space: nowrap; }}
  .empty-plate {{
    text-align: center;
    padding: 3rem 1rem;
    color: var(--waffle-base);
  }}
  .empty-plate .waffle-icon {{ margin-bottom: 1rem; }}
  footer {{
    max-width: 1400px;
    margin: 0 auto 2rem;
    padding: 0 1.5rem;
    text-align: center;
    color: var(--waffle-base);
    font-size: 0.85rem;
  }}
  footer .waffle-icon {{ width: 20px; height: 20px; vertical-align: middle; margin: 0 2px; opacity: 0.7; }}
  code {{ background: var(--waffle-mist); padding: 0.1rem 0.4rem; border-radius: 4px; }}
  @media (max-width: 640px) {{
    table {{ font-size: 0.85rem; }}
    .col-updated, .col-author {{ display: none; }}
  }}
  .pagination {{
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1.5rem;
    padding: 1.25rem;
    background: var(--waffle-mist);
    border-top: 1px solid var(--waffle-light);
  }}
  .pagination button {{
    background: var(--waffle-base);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: background 0.15s ease, transform 0.1s ease;
  }}
  .pagination button:hover:not(:disabled) {{
    background: var(--waffle-deep);
    transform: translateY(-1px);
  }}
  .pagination button:active:not(:disabled) {{
    transform: translateY(0);
  }}
  .pagination button:disabled {{
    background: var(--waffle-pale);
    color: var(--waffle-light);
    cursor: not-allowed;
    box-shadow: none;
  }}
  .pagination-info {{
    font-size: 0.95rem;
    color: var(--waffle-dark);
    font-weight: 600;
    user-select: none;
  }}
  .pr-tooltip {{
    position: absolute;
    display: none;
    background: #1e1e1e;
    color: #f5f5f5;
    border: 1px solid #444;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.35);
    pointer-events: auto;
    max-width: 950px;
    max-height: 700px;
    overflow-y: auto;
    overscroll-behavior: contain;
    z-index: 1000;
    font-size: 0.85rem;
    line-height: 1.4;
  }}
  .pr-tooltip-title {{
    font-weight: 700;
    font-size: 0.95rem;
    margin-top: 0;
    margin-bottom: 0.5rem;
    color: var(--waffle-light);
    border-bottom: 1px solid #444;
    padding-bottom: 0.25rem;
  }}
  .pr-tooltip-body {{
    font-family: inherit;
    margin: 0;
    color: #e0e0e0;
  }}
  .pr-tooltip-body p {{
    margin-top: 0;
    margin-bottom: 0.75rem;
  }}
  .pr-tooltip-body code {{
    background: #2d2d2d;
    color: #f8f8f2;
    padding: 0.1rem 0.3rem;
    border-radius: 3px;
    font-family: monospace;
    font-size: 0.85rem;
  }}
  .pr-tooltip-body pre {{
    background: #2d2d2d;
    padding: 0.75rem;
    border-radius: 6px;
    overflow-x: auto;
    margin-top: 0.5rem;
    margin-bottom: 0.75rem;
  }}
  .pr-tooltip-body pre code {{
    background: transparent;
    padding: 0;
    border-radius: 0;
    font-size: 0.85rem;
  }}
  .pr-tooltip-body h1, .pr-tooltip-body h2, .pr-tooltip-body h3 {{
    margin-top: 1rem;
    margin-bottom: 0.5rem;
    color: var(--waffle-light);
    font-size: 1rem;
  }}
  .pr-tooltip-body ul, .pr-tooltip-body ol {{
    margin-top: 0.25rem;
    margin-bottom: 0.75rem;
    padding-left: 1.25rem;
  }}
  .pr-tooltip-body li {{
    margin-bottom: 0.25rem;
  }}
  .pr-tooltip-body a {{
    color: var(--waffle-light);
    text-decoration: underline;
  }}
  .pr-tooltip-body a:hover {{
    color: white;
  }}
</style>
</head>
<body>
  <svg style="position: absolute; width: 0; height: 0; overflow: hidden;" version="1.1" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="body-row" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{WAFFLE_MID}"/>
        <stop offset="100%" stop-color="{WAFFLE_BASE}"/>
      </linearGradient>
      <linearGradient id="pocket-row" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{WAFFLE_DEEP}"/>
        <stop offset="100%" stop-color="{WAFFLE_DARK}"/>
      </linearGradient>
      <linearGradient id="body-hero" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{WAFFLE_MID}"/>
        <stop offset="100%" stop-color="{WAFFLE_BASE}"/>
      </linearGradient>
      <linearGradient id="pocket-hero" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{WAFFLE_DEEP}"/>
        <stop offset="100%" stop-color="{WAFFLE_DARK}"/>
      </linearGradient>
    </defs>
  </svg>
  <div class="hero">
    <div class="hero-icons">{icon_lg}{icon_lg}{icon_lg}</div>
    <h1>Intrinsic Triage Board</h1>
    <p>Unassigned, unlabeled intrinsic-ai and intrinsic-opensource pull requests waiting for a reviewer.</p>
    <a href="{repo_url}" target="_blank" rel="noopener" class="repo-link" title="View Source on GitHub">
      <svg class="github-logo" viewBox="0 0 16 16" version="1.1" width="24" height="24" aria-hidden="true" fill="currentColor">
        <path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.35 3.12.88.01.64.01 1.11.01 1.28 0 .21-.15.46-.55.38A8.013 8.013 0 0 1 0 8c0-4.42 3.58-8 8-8z"></path>
      </svg>
    </a>
    <br>
    <span class="badge">{badge_text}</span>
  </div>
  <main>
{sections_html}
  </main>
  <footer>
    {icon_sm}{icon_sm}{icon_sm}
    <p>Generated {generated_at.strftime('%b %d, %Y %H:%M UTC')} by <code>baffle_maker</code>.</p>
  </footer>
  <script>
    const GENERATED_AT = "{generated_at.isoformat()}";
    document.addEventListener('DOMContentLoaded', () => {{
      const checkboxes = document.querySelectorAll('.waffle-container input[type="checkbox"]');
      checkboxes.forEach(cb => {{
        const url = cb.getAttribute('data-url');
        if (localStorage.getItem(url) === 'true') {{
          cb.checked = true;
        }}
        cb.addEventListener('change', (e) => {{
          if (e.target.checked) {{
            localStorage.setItem(url, 'true');
          }} else {{
            localStorage.removeItem(url);
          }}
        }});
      }});

      // Pagination
      const PAGE_SIZE = 10;
      const TWO_WEEKS_MS = 14 * 24 * 60 * 60 * 1000;
      const generatedDate = new Date(GENERATED_AT);

      const groups = document.querySelectorAll('section.group');
      groups.forEach(group => {{
        const tbody = group.querySelector('tbody');
        if (!tbody) return;
        const rows = Array.from(tbody.querySelectorAll('tr:not(.empty-fortnight-row)'));
        const placeholderRow = tbody.querySelector('.empty-fortnight-row');
        
        // Separate rows into recent (last 2 weeks) and older
        const recentRows = [];
        const olderRows = [];
        
        rows.forEach(row => {{
          const updatedStr = row.getAttribute('data-updated');
          if (updatedStr) {{
            const updatedDate = new Date(updatedStr);
            if (generatedDate - updatedDate <= TWO_WEEKS_MS) {{
              recentRows.push(row);
            }} else {{
              olderRows.push(row);
            }}
          }} else {{
            olderRows.push(row);
          }}
        }});

        // Determine total pages. Page 1 is recentRows. Pages 2+ are olderRows.
        const olderPages = Math.ceil(olderRows.length / PAGE_SIZE);
        const totalPages = 1 + olderPages;

        // If totalPages is 1 (meaning 0 older rows, and we have some recent rows),
        // we don't need pagination controls.
        if (totalPages === 1) {{
          recentRows.forEach(row => row.style.display = '');
          if (placeholderRow) placeholderRow.style.display = 'none';
          return;
        }}

        let currentPage = 1;

        const paginationDiv = document.createElement('div');
        paginationDiv.className = 'pagination';

        const prevBtn = document.createElement('button');
        prevBtn.textContent = '◀ Prev';
        prevBtn.disabled = true;

        const infoSpan = document.createElement('span');
        infoSpan.className = 'pagination-info';

        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next ▶';

        paginationDiv.appendChild(prevBtn);
        paginationDiv.appendChild(infoSpan);
        paginationDiv.appendChild(nextBtn);
        group.appendChild(paginationDiv);

        function showPage(page) {{
          currentPage = page;
          
          // Hide everything first
          rows.forEach(r => r.style.display = 'none');
          if (placeholderRow) placeholderRow.style.display = 'none';

          if (currentPage === 1) {{
            if (recentRows.length > 0) {{
              recentRows.forEach(r => r.style.display = '');
            }} else {{
              if (placeholderRow) placeholderRow.style.display = '';
            }}
          }} else {{
            const startIdx = (currentPage - 2) * PAGE_SIZE;
            const endIdx = startIdx + PAGE_SIZE;
            olderRows.slice(startIdx, endIdx).forEach(r => r.style.display = '');
          }}

          prevBtn.disabled = (currentPage === 1);
          nextBtn.disabled = (currentPage === totalPages);
          infoSpan.textContent = `Page ${{currentPage}} of ${{totalPages}}`;
        }}

        prevBtn.addEventListener('click', () => {{
          if (currentPage > 1) showPage(currentPage - 1);
        }});

        nextBtn.addEventListener('click', () => {{
          if (currentPage < totalPages) showPage(currentPage + 1);
        }});

        showPage(1);
      }});

      // Tooltip handling
      const tooltip = document.createElement('div');
      tooltip.className = 'pr-tooltip';
      document.body.appendChild(tooltip);

      let hideTimeout = null;

      const repoCells = document.querySelectorAll('tbody td.col-repo');
      
      const showTooltip = (cell) => {{
        if (hideTimeout) {{
          clearTimeout(hideTimeout);
          hideTimeout = null;
        }}
        const row = cell.closest('tr');
        const title = row.getAttribute('data-title');
        const body = row.getAttribute('data-body') || 'No description provided.';
        
        tooltip.innerHTML = `
          <div class="pr-tooltip-title">${{title}}</div>
          <div class="pr-tooltip-body">${{marked.parse(body)}}</div>
        `;
        tooltip.style.display = 'block';
      }};

      const hideTooltip = () => {{
        hideTimeout = setTimeout(() => {{
          tooltip.style.display = 'none';
        }}, 100);
      }};

      repoCells.forEach(cell => {{
        cell.addEventListener('mouseenter', () => {{
          showTooltip(cell);
        }});

        cell.addEventListener('mousemove', (e) => {{
          const tooltipWidth = tooltip.offsetWidth;
          const tooltipHeight = tooltip.offsetHeight;
          const pageX = e.pageX;
          const pageY = e.pageY;
          
          let x = pageX + 15;
          let y = pageY + 15;
          
          if (x + tooltipWidth > window.innerWidth + window.scrollX) {{
            x = pageX - tooltipWidth - 15;
          }}
          if (y + tooltipHeight > window.innerHeight + window.scrollY) {{
            y = pageY - tooltipHeight - 15;
          }}
          
          tooltip.style.left = `${{x}}px`;
          tooltip.style.top = `${{y}}px`;
        }});

        cell.addEventListener('mouseleave', (e) => {{
          if (e.relatedTarget === tooltip || tooltip.contains(e.relatedTarget)) {{
            if (hideTimeout) clearTimeout(hideTimeout);
            return;
          }}
          hideTooltip();
        }});

        cell.addEventListener('wheel', (e) => {{
          if (tooltip.style.display === 'block' && tooltip.scrollHeight > tooltip.clientHeight) {{
            tooltip.scrollTop += e.deltaY;
            e.preventDefault();
          }}
        }}, {{ passive: false }});
      }});

      tooltip.addEventListener('mouseenter', () => {{
        if (hideTimeout) {{
          clearTimeout(hideTimeout);
          hideTimeout = null;
        }}
      }});

      tooltip.addEventListener('mouseleave', (e) => {{
        const targetCell = e.relatedTarget ? e.relatedTarget.closest('td.col-repo') : null;
        if (targetCell) {{
          return;
        }}
        tooltip.style.display = 'none';
      }});
    }});
  </script>
</body>
</html>
'''


def write_site(html_content, site_dir):
    out_path = os.path.join(site_dir, 'index.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print('Wrote %s' % out_path)


def main():
    workspace = os.environ.get('BUILD_WORKSPACE_DIRECTORY', os.getcwd())
    site_dir = os.path.join(workspace, 'site')
    os.makedirs(site_dir, exist_ok=True)

    data_path = sys.argv[1] if len(sys.argv) > 1 else find_latest_analyzed_file(site_dir)
    if not data_path:
        print("Error: no analyzed YAML file found in %s. Run the query and analyze tools first." % site_dir, file=sys.stderr)
        return 1

    with open(data_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    html_content = render_html(data, datetime.datetime.now(datetime.timezone.utc))
    write_site(html_content, site_dir)

    return 0


if __name__ == '__main__':
    sys.exit(main())
