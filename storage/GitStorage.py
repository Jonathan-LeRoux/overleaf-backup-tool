import os
import logging
import time
import requests
import json
import git
from git import Repo
from urllib.parse import urljoin

RETRY = 3


def is_git_repo(path):
    try:
        _ = git.Repo(path).git_dir
        return True
    except git.exc.InvalidGitRepositoryError:
        return False


def call_rhodecode(base_uri, auth_token, method, args, verbose):
    headers = {'content-type': 'application/json'}
    url = base_uri + '_admin/api'
    payload = {
        'auth_token': auth_token,
        'method': method,
        'args': args,
        'id': 1,
    }
    if verbose:
        print('Calling Rhodecode with payload: ', payload)
    r = requests.post(url, data=json.dumps(payload), headers=headers)
    if verbose:
        print('Rhodecode response: ' + r.text)
    return {
        'result': r.json()['result'],
        'error': r.json()['error']
    }


def get_github_repo_api_url(remote_api_uri, remote_path, repo_name, github_username, github_orgname):
    if not github_orgname:
        github_owner = github_username
    else:
        github_owner = github_orgname
    api_url = urljoin(remote_api_uri, 'repos/' + '/'.join([github_owner, remote_path]) + repo_name)
    return api_url


def get_github_repo_html_url(remote_api_uri, remote_path, repo_name, github_username, github_orgname):
    if not github_orgname:
        github_owner = github_username
    else:
        github_owner = github_orgname
    repo_uri = remote_api_uri.replace('https://','').replace('api.','').replace('api/v3','')
    repo_url = urljoin(repo_uri, '/'.join([github_owner, remote_path]) + repo_name)
    return repo_url


def create_github_repo(base_uri, remote_path, repo_name, github_username, auth_token, github_orgname, verbose):
    auth = (github_username, auth_token)
    headers = {'Accept': 'application/vnd.github.v3+json'}
    if not github_orgname:
        remote_api_uri = urljoin(base_uri, 'user/repos')
    else:
        remote_api_uri = urljoin(base_uri, 'org/{}/repos'.format(github_orgname))

    payload = {
        'name': remote_path + repo_name,
        'description': 'Backup for Overleaf repo {}'.format(repo_name),
        'private': True,
        'auto_init': False
    }
    if verbose:
        print('Calling Github with payload: ', payload)
    r = requests.post(remote_api_uri, data=json.dumps(payload),
                      auth=auth, headers=headers)
    if verbose:
        print('Github response: ' + r.text)
    return r


def rename_github_repo(base_uri, old_repo_name, remote_path, repo_name, github_username, auth_token, github_orgname, verbose):
    auth = (github_username, auth_token)
    headers = {'Accept': 'application/vnd.github.v3+json'}
    old_remote_repo_url = get_github_repo_api_url(base_uri, remote_path, old_repo_name,
                                                  github_username, github_orgname)
    payload = {
        'name': remote_path + repo_name,
        'description': 'Backup for Overleaf repo {}'.format(repo_name)
    }
    if verbose:
        print('Calling Github with payload: ', payload)
    r = requests.patch(old_remote_repo_url, data=json.dumps(payload),
                      auth=auth, headers=headers)
    if verbose:
        print('Github response: ' + r.text)
    return r


def create_or_update_local_backup(git_url, repo_dir):
    if not os.path.isdir(repo_dir):
        # Create folder with parents
        os.makedirs(repo_dir)
    if is_git_repo(repo_dir) or not os.listdir(repo_dir):
        # Folder is either already a git repo (then pull) or empty (then clone)
        for i in range(1, RETRY + 1):
            try:
                if is_git_repo(repo_dir):
                    # pull
                    myrepo = Repo(repo_dir)
                    origin_url = myrepo.remotes['origin'].url
                    if origin_url == git_url:
                        myrepo.remotes['origin'].pull()
                    else:
                        logging.exception("Folder {0} is a git repo but does not correspond to this Overleaf project."
                                          "Origin is {1} instead of {2}.".format(repo_dir, origin_url, git_url))
                        raise RuntimeError
                elif not os.listdir(repo_dir):
                    # existing but empty folder: clone
                    Repo.clone_from(git_url, repo_dir)
            except git.GitCommandError as ex:
                logging.info("error:{0}: retry:{1}/{2}".format(ex, i, RETRY))
                time.sleep(2)
                logging.info("retrying")
            except RuntimeError:
                # Get out of the retry loop
                break
            else:
                return True
        else:
            logging.exception("Max retry count reached without success")
        # We should only reach this if max retry count was reached without success or the git repo did not match
        raise RuntimeError
    else:
        # Existing non empty folder that is not already a git repo: we can't do anything
        logging.exception("Specified folder {0} is not empty and not a git repo, "
                          "we cannot clone into it".format(repo_dir))
        raise RuntimeError


def push_to_remote(remote_api_uri, remote_path, remote_name, remote_type, auth_token, repo_name, repo_dir,
                   old_repo_name=None, github_username=None, github_orgname=None, verbose=False):
    if os.path.isdir(repo_dir):
        for i in range(1, RETRY + 1):
            try:
                myrepo = Repo(repo_dir)
                if remote_type == 'rc':
                    remote_repo_url = urljoin(remote_api_uri, '/'.join([remote_path, repo_name]))
                else: # Github, just concatenate the prefix specified by remote_path with repo_name
                    remote_repo_url = get_github_repo_html_url(remote_api_uri, remote_path, repo_name,
                                                               github_username, github_orgname)
                remote_uri_and_path_changed = False
                if remote_name in myrepo.remotes:
                    old_remote_url = myrepo.remotes[remote_name].url
                    if remote_type == 'rc':
                        remote_uri_and_path = urljoin(remote_api_uri, remote_path)
                        if not old_remote_url.startswith(remote_uri_and_path):
                            remote_uri_and_path_changed = True
                    else: # Github: not a very strict test, but I'm unsure the repo URL always starts with https://
                        if not get_github_repo_html_url(remote_api_uri, remote_path, '',
                                                        github_username, github_orgname) in old_remote_url:
                            remote_uri_and_path_changed = True
                if remote_name not in myrepo.remotes or old_repo_name is not None or remote_uri_and_path_changed:
                    # We need to either create or rename the repo on the remote
                    repo_created = False
                    if remote_type == 'rc':
                        result_dict = {'error': {}}  # unnecessary, as result_dict should get defined below in all cases
                        if remote_name not in myrepo.remotes or remote_uri_and_path_changed:
                            # create repo on the remote
                            rc_args = {
                                'repo_name': '/'.join([remote_path, repo_name]),
                                'repo_type': 'git',
                                'description': 'Backup for Overleaf repo {}'.format(repo_name),
                                'copy_permissions': True
                            }
                            result_dict = call_rhodecode(remote_api_uri, auth_token, 'create_repo', rc_args, verbose)
                        elif old_repo_name is not None:
                            # We need to rename the repo because the project name changed on Overleaf
                            rc_args = {
                                'repoid': '/'.join([remote_path, old_repo_name]),
                                'repo_name': '/'.join([remote_path, repo_name]),
                                'description': 'Backup for Overleaf repo {}'.format(repo_name),
                            }
                            result_dict = call_rhodecode(remote_api_uri, auth_token, 'update_repo', rc_args, verbose)

                        # We assume the call is successful either if it did create the repo or gave an error
                        # because a repo with the same name already existed (not super safe??)
                        if result_dict['error'] is None or 'unique_repo_name' in result_dict['error']:
                            repo_created = True
                            if result_dict['result'] is not None and 'msg' in result_dict['result']:
                                logging.info("Remote responded: {}".format(result_dict['result']['msg']))

                    elif remote_type == 'github':
                        if remote_name not in myrepo.remotes or remote_uri_and_path_changed:
                            # create repo on the remote
                            result = create_github_repo(remote_api_uri, remote_path, repo_name,
                                                        github_username, auth_token, github_orgname, verbose)

                        elif old_repo_name is not None:
                            # We need to rename the repo because the project name changed on Overleaf
                            result = rename_github_repo(remote_api_uri, old_repo_name, remote_path, repo_name,
                                                        github_username, auth_token, github_orgname, verbose)
                        # We assume the call is successful either if it did create the repo or gave an error
                        # because a repo with the same name already existed (not super safe??)
                        if 'message' not in result or \
                                ('errors' in result and 'name already exists' in result['errors'][0]['message']):
                            repo_created = True
                    # add remote to repo
                    if repo_created:
                        if remote_name not in myrepo.remotes:
                            myrepo.create_remote(remote_name, remote_repo_url)
                        else:
                            myrepo.remotes[remote_name].set_url(remote_repo_url)

                # push
                myrepo.remotes[remote_name].push()
            except git.GitCommandError as ex:
                logging.info("error:{0}: retry:{1}/{2}".format(ex, i, RETRY))
                time.sleep(2)
                logging.info("retrying")
            else:
                return True
        else:
            logging.exception("max retry count reached without success")
            raise RuntimeError
    else:
        logging.exception("Local folder {} does not exist".format(repo_dir))
        raise OSError
