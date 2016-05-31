#!/usr/bin/python3.4
import sys
import os
import asyncio
import json
from asyncio.subprocess import DEVNULL, PIPE, STDOUT

try:
    import gitlab
    import aiohttp
except Exception as e:
    print(e)
    print("""You have to install pyapi-gitlab and aiohttp:\n"""
          """pip3 install pyapi-gitlab\npip3 install aiohttp""")
    sys.exit(1)

CONCUR_UPDATES = 7
USAGE = "./clone_group.py group_name group_dir"
TOKEN = ''
URL   = 'https://gitlab.i-free.com'
GIT = gitlab.Gitlab(URL, token = TOKEN)
HEADERS = {"PRIVATE-TOKEN": TOKEN}
API_URL = URL + '/api/v3'
GROUPS_URL = API_URL + '/groups'
PROJECT_URL = API_URL + '/projects'
FAIL_COL = '\033[91m'
END_COL = '\033[0m'


def group_repo(group_name):
    groups = GIT.getgroups()
    for group in groups:
        if group['path'] == group_name:
            return GIT.getgroups(group['id'])['projects']


@asyncio.coroutine
def getrepositorycommits(project_id, ref_name='master', page=0, per_page=1):
    payload = {'page': page, 'per_page': per_page, 'ref_name': ref_name}
    resp = yield from aiohttp.request('GET', "{0}/{1}/repository/commits".format(
              PROJECT_URL, project_id), data=json.dumps(payload), headers=HEADERS)
    if resp.status == 200:
        text = yield from resp.json()
        return text
    else:
        return False


@asyncio.coroutine
def proc_call(cmd, **kwargs):
    proc = yield from asyncio.create_subprocess_shell(cmd, **kwargs)
    stdout, stderr = yield from proc.communicate()
    exitcode = yield from proc.wait()
    return (stdout, exitcode)


@asyncio.coroutine
def get_ci(prj):
    get_ci = yield from getrepositorycommits(prj['id'], page=0, per_page=1)
    last_ci = get_ci[0]['id'] if len(get_ci) > 0 else []
    prj['last_ci'] = last_ci
    return prj

def print_result(status, prj_name, output, cmd):
    msg = {'fail': {'clone': 'Failed to clone {0}',
                    'fetch': 'Failed to fetch {0}',
                    'merge': 'Failed to merge {0}',
                    'chlog': "Couldn't check last local commit in project {0}"},
           'success': {'clone': '{0} was cloned',
                       'merge': '{0} was updated'}
          }
    if status == 0 and cmd in msg['success']:
        print(msg['success'][cmd].format(prj_name))
    elif status != 0:
        print(FAIL_COL + msg['fail'][cmd].format(prj_name) + END_COL)
        print(FAIL_COL + output.decode('utf-8') + END_COL)

@asyncio.coroutine
def check_prj(prj, path):
    name = prj['name']
    rlast_ci = prj['last_ci']
    git_path = prj['ssh_url_to_repo']
    full_path = path + '/' + name
    clone = 'git clone {0} {1}'.format(git_path, full_path)
    fetch = 'git fetch'
    merge = 'git merge origin/master'
    llast_ci_cmd = 'git log -n 1 --pretty=format:%H'
    
    if not os.path.isdir(path):
        os.mkdir(path)
    if os.path.isdir(full_path) == False:
        output, status = yield from proc_call(clone, stdout=PIPE, stderr=STDOUT)
        print_result(status, name, output, 'clone')
    elif len(rlast_ci) == 0:
        return
    else:
        llast_ci, status = yield from proc_call(llast_ci_cmd, stdout=PIPE,
                                stderr=STDOUT, cwd=full_path)
        print_result(status, name, llast_ci, 'chlog')
        if llast_ci.decode('utf-8') != rlast_ci:
            output, status = yield from proc_call(fetch, stdout=PIPE,
                                                  stderr=STDOUT,
                                                  cwd=full_path)
            print_result(status, name, output, 'fetch')
            if status == 0:
                output, status = yield from proc_call(merge, stdout=PIPE,
                                     stderr=STDOUT, cwd=full_path)
                print_result(status, name, output, 'merge')


@asyncio.coroutine
def update_project(prj, path, semaphore):
    yield from get_ci(prj)
    with (yield from semaphore):
        yield from check_prj(prj, path)


def main(group, path):
    projects = group_repo(group)
    semaphore = asyncio.Semaphore(CONCUR_UPDATES)
    loop = asyncio.get_event_loop()
    tasks = [loop.create_task(update_project(prj, path, semaphore))
             for prj in projects]
    loop.run_until_complete(asyncio.wait(tasks))
    loop.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Not enough arguments')
        print('USAGE: ' + USAGE)
        sys.exit(1)
    group = sys.argv[1]
    path  = sys.argv[2]
    main(group, path)
