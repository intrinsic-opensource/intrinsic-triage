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

"""Queries the GitHub API for open ROS 2 / ament pull requests and their
authors, and saves the result to a dated YAML file in the site directory.

If a YAML file for today's date already exists, the query is skipped
entirely so repeated runs on the same day don't hammer the GitHub API.
"""

import datetime
import os
import sys

import yaml
from github import Github
from github import Auth
from github import GithubException

from common import DATE_FILE_FORMAT
from common import ORGS
from common import ROS_MAINTAINER_OVERRIDES
from common import repo_from_url

excluded_labels = [
    'backlog',
    'help wanted',
    'more-information-needed',
]

excluded_repos = []

excluded_projects = ['ros2/52']


def build_search(weeks=None):
    search_terms = []
    for org in ORGS:
        search_terms.append('org:' + org)
    for xlabel in excluded_labels:
        search_terms.append('-label:"' + xlabel + '"')
    for xrepo in excluded_repos:
        search_terms.append('-repo:' + xrepo)
    for xproj in excluded_projects:
        search_terms.append('-project:' + xproj)
    
    search = ' '.join(search_terms) + ' state:open is:pr no:assignee -draft:true archived:false'
    
    if weeks is not None:
        today = datetime.date.today()
        start_delta = datetime.timedelta(weeks=weeks)
        start_day = today - start_delta
        updatestring = 'updated:>=%s' % start_day
        search += ' ' + updatestring

    return search


def fetch_pull_requests(gh, search):
    rows = []
    for issue in gh.search_issues(search):
        url = issue.html_url
        if issue.pull_request is not None:
            kind = 'PR'
        else:
            kind = 'Issue'
        rows.append({
            'repo': repo_from_url(url),
            'title': issue.title,
            'url': url,
            'kind': kind,
            'author': issue.user.login if issue.user else 'unknown',
            'created': issue.created_at.isoformat(),
            'updated': issue.updated_at.isoformat(),
            'body': issue.body or '',
        })
    # Sort by updated time in descending order (most recently updated first)
    rows.sort(key=lambda r: r['updated'], reverse=True)
    return rows


def fetch_org_members(gh, orgs):
    """Return the set of publicly-visible usernames across the given orgs."""
    members = set()
    for org in orgs:
        for member in gh.get_organization(org).get_members():
            members.add(member.login)
    return members


def fetch_user_stats(gh, username, org_members):
    now = datetime.datetime.now(datetime.timezone.utc)
    stats = {
        'account_created_at': None,
        'account_age_days': 0,
        'public_pull_requests': 0,
        'public_issues': 0,
        'public_reviews': 0,
        'is_ros_maintainer': username in org_members or username in ROS_MAINTAINER_OVERRIDES,
        # True when GitHub excludes this account from its search API (a
        # flagged/restricted account: the profile still resolves but an
        # author-qualified search 422s). analyze.py falls back to the
        # PR-burst heuristic for these users.
        'search_restricted': False,
        'last_updated_at': now.isoformat(),
    }

    try:
        user = gh.get_user(username)
        created_at = user.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        stats['account_created_at'] = created_at.isoformat()
        stats['account_age_days'] = (now - created_at).days
    except GithubException as e:
        if e.status not in (404, 422):
            raise e
        print(f"Warning: failed to fetch profile for user {username}: {e}", file=sys.stderr)
        stats['search_restricted'] = True
        return stats

    # Kept separate from the profile lookup above so a search 422 doesn't
    # discard the account age we just resolved.
    try:
        stats['public_pull_requests'] = gh.search_issues('is:pr is:public author:%s' % username).totalCount
        stats['public_issues'] = gh.search_issues('is:issue is:public author:%s' % username).totalCount
        stats['public_reviews'] = gh.search_issues('is:pr is:public reviewed-by:%s' % username).totalCount
    except GithubException as e:
        if e.status not in (404, 422):
            raise e
        print(f"Warning: search restricted for user {username}: {e}", file=sys.stderr)
        stats['search_restricted'] = True

    return stats


def data_file_path(site_dir, today):
    return os.path.join(site_dir, today.strftime(DATE_FILE_FORMAT) + '.yaml')


USER_CACHE_FILENAME = 'user_cache.yaml'
USER_CACHE_EXPIRATION_DAYS = 30


def load_user_cache(site_dir):
    cache_path = os.path.join(site_dir, USER_CACHE_FILENAME)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: failed to load user cache from {cache_path}: {e}", file=sys.stderr)
    return {}


def save_user_cache(site_dir, cache):
    cache_path = os.path.join(site_dir, USER_CACHE_FILENAME)
    try:
        os.makedirs(site_dir, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(cache, f, sort_keys=False)
        print(f"Saved user cache to {cache_path}")
    except Exception as e:
        print(f"Error: failed to save user cache to {cache_path}: {e}", file=sys.stderr)


def main():
    workspace = os.environ.get('BUILD_WORKSPACE_DIRECTORY', os.getcwd())
    site_dir = os.path.join(workspace, 'site')

    import argparse
    parser = argparse.ArgumentParser(description="Query GitHub for ROS 2 / ament PRs")
    parser.add_argument("out_path", nargs="?", help="Path to write query results")
    parser.add_argument("--weeks", type=int, default=None, help="Number of weeks to go back (default: all time)")
    parser.add_argument("--force", action="store_true", help="Force run even if already updated today")
    args = parser.parse_args()

    if args.out_path:
        out_path = args.out_path
        if not os.path.isabs(out_path):
            out_path = os.path.join(workspace, out_path)
    else:
        out_path = os.path.join(site_dir, 'issue_cache.yaml')

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

    # Skip if run on the same day to avoid hammering API (unless --force is passed)
    if not args.force and os.path.exists(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as f:
                old_data = yaml.safe_load(f) or {}
                if 'generated_at' in old_data:
                    last_gen = datetime.datetime.fromisoformat(old_data['generated_at']).date()
                    if last_gen == datetime.date.today():
                        print(f"Issue cache {out_path} was already updated today ({last_gen}). Skipping query.")
                        return 0
        except Exception as e:
            pass

    # Load existing issue cache if it exists
    old_pull_requests = []
    if os.path.exists(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as f:
                old_data = yaml.safe_load(f) or {}
                old_pull_requests = old_data.get('pull_requests', [])
        except Exception as e:
            print(f"Warning: failed to load existing issue cache from {out_path}: {e}", file=sys.stderr)

    key = os.environ.get('GITHUB_API_TOKEN')
    if not key:
        print("Error: GITHUB_API_TOKEN environment variable is not set.", file=sys.stderr)
        print("Please set it in your environment: export GITHUB_API_TOKEN=\"your_token\"", file=sys.stderr)
        return 1

    auth = Auth.Token(key)
    gh = Github(auth=auth)

    search = build_search(weeks=args.weeks)
    print("Search:", search)
    pull_requests = fetch_pull_requests(gh, search)
    for row in pull_requests:
        print('%s,"%s"' % (row['url'], row['title']))

    # Merge existing PRs with newly fetched ones
    existing_prs = {pr['url']: pr for pr in old_pull_requests}
    fetched_urls = {pr['url'] for pr in pull_requests}

    for pr in pull_requests:
        existing_prs[pr['url']] = pr

    if args.weeks is not None:
        today = datetime.date.today()
        start_delta = datetime.timedelta(weeks=args.weeks)
        start_day = today - start_delta
        start_day_str = start_day.isoformat()

        pruned_prs = {}
        for url, pr in existing_prs.items():
            # If the PR was updated within our search window, but not found in the search, remove it
            if pr['updated'][:10] >= start_day_str and url not in fetched_urls:
                continue
            pruned_prs[url] = pr
        existing_prs = pruned_prs
    else:
        # If weeks is None (all-time search), we only keep the newly fetched ones
        # because the search is comprehensive.
        existing_prs = {pr['url']: pr for pr in pull_requests}

    merged_pull_requests = list(existing_prs.values())
    merged_pull_requests.sort(key=lambda r: r['updated'], reverse=True)

    user_cache = load_user_cache(site_dir)
    now = datetime.datetime.now(datetime.timezone.utc)
    cache_updated = False
    org_members = None

    usernames = sorted({row['author'] for row in merged_pull_requests})
    users = {}
    for username in usernames:
        cached_user = user_cache.get(username)
        needs_query = True

        if cached_user and 'last_updated_at' in cached_user:
            try:
                last_updated = datetime.datetime.fromisoformat(cached_user['last_updated_at'])
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=datetime.timezone.utc)
                if (now - last_updated).days < USER_CACHE_EXPIRATION_DAYS:
                    needs_query = False
            except Exception as e:
                print(f"Warning: failed to parse last_updated_at for {username}, will re-query: {e}")

        if needs_query:
            print('Fetching stats for user:', username)
            if org_members is None:
                print('Fetching org members for:', ', '.join(ORGS))
                org_members = fetch_org_members(gh, ORGS)

            try:
                stats = fetch_user_stats(gh, username, org_members)
                user_cache[username] = stats
                cache_updated = True
            except Exception as e:
                print(f"Error: failed to fetch stats for user {username}: {e}", file=sys.stderr)
                if cached_user:
                    print(f"Falling back to expired cached stats for user {username}")
                    stats = cached_user
                else:
                    raise e
        else:
            stats = cached_user
            if stats.get('account_created_at'):
                try:
                    created_at = datetime.datetime.fromisoformat(stats['account_created_at'])
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=datetime.timezone.utc)
                    stats['account_age_days'] = (now - created_at).days
                except Exception as e:
                    print(f"Warning: failed to recalculate account age for {username}: {e}")

        users[username] = stats

    if cache_updated:
        save_user_cache(site_dir, user_cache)

    data = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'search': search,
        'pull_requests': merged_pull_requests,
        'users': users,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)
    print('Wrote %s' % out_path)

    return 0


if __name__ == '__main__':
    sys.exit(main())
