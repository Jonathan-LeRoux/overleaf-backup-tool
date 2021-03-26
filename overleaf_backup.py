import json
import click
import pickle
import re

from clients.OverleafClient import OverleafClient
from storage.GitStorage import GitStorage
from utils.debug import enable_http_client_debug, is_debug

import os
import sys
import logging

# From https://github.com/django/django/blob/main/django/utils/text.py
def get_valid_filename(s):
    """
    Return the given string converted to a string that can be used for a clean
    filename. Remove leading and trailing spaces; convert other spaces to
    underscores; and remove anything that is not an alphanumeric, dash,
    underscore, or dot.
    >>> get_valid_filename("john's portrait in 2004.jpg")
    'johns_portrait_in_2004.jpg'
    """
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)

def limit_folder_name_length(folder_name, max_length=40):
    if len(folder_name) > max_length:
        folder_name = folder_name[:max_length]
    return folder_name

@click.command()
# @click.option('-u', '--username', required=False,
#               prompt="Username (type anything if already logged in, delete cookie and start again if needed)",
#               help="You Overleaf username. Will NOT be stored or used for anything else.")
# @click.option('-p', '--password', hide_input=True, required=False,
#               prompt="Password (type anything if already logged in, delete cookie and start again if needed)",
#               help="You Overleaf password. Will NOT be stored or used for anything else.")
@click.option('-c', '--cookie-path', default="", type=click.Path(exists=False),
              help="Relative path to save/load the persisted Overleaf cookie.")
@click.option('-b', '--backup-dir', default="./", type=click.Path(exists=True),
              help="Path of folder in which to store git backups.")
@click.option('--include-archived/--ignore-archived', 'include_archived', default=False,
              help="Download archived projects as well (Default: No).")
@click.option('--verbose/--non-verbose', 'verbose', default=False,
              help="Verbose mode (Default: No).")
@click.option('-u', '--remote-api-uri', default="", type=str,
              help="Path to remote API if pushing git repos to another remote.")
@click.option('-r', '--remote-path', default="", type=str,
              help="Path (without base URI) to subfolder for pushing git repos to another remote.")
@click.option('-a', '--auth-token', default="", type=str,
              help="Auth token for remote API access for pushing git repos.")
@click.option('-n', '--remote-name', default="rc", type=str,
              help="Name (within git) of remote for pushing git repos to another remote.")
@click.option('-t', '--remote-type', default="rc", type=click.Choice(['rc', 'github'], case_sensitive=False),
              help="Type other remote for pushing git repos (either 'rc' or 'github').")
def main(cookie_path, backup_dir, include_archived, remote_api_uri,
         remote_path, remote_type, remote_name, auth_token, verbose):
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)

    verbose = is_debug() or verbose
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        enable_http_client_debug()  # log http requests

    backup_git_dir = "git_backup/"

    if not backup_dir.endswith("/"):
        backup_dir = backup_dir + "/"

    if remote_path and not remote_api_uri.endswith("/"):
        remote_api_uri = remote_api_uri + "/"
    pushed_to_remote_key = "pushed_to_remote_{}".format(remote_name)

    backup_git_dir = os.path.join(backup_dir, backup_git_dir)

    if not os.path.isfile(cookie_path):
        username = click.prompt("Username")
        password = click.prompt("Password", hide_input=True)
        overleaf_client = OverleafClient()
        store = overleaf_client.login_with_user_and_pass(username, password)
        if store is None:
            return False
        if cookie_path:
            # Only store if a path is provided
            with open(cookie_path, 'wb+') as f:
                pickle.dump(store, f)
    else:
        logging.info("Using stored credentials, please delete {} if you would like to login again".format(cookie_path))
        with open(cookie_path, 'rb') as f:
            store = pickle.load(f)

        overleaf_client = OverleafClient(store["cookie"], store["csrf"])

    projects_info_list = overleaf_client.all_projects(include_archived=include_archived)

    logging.info("Total projects: %s" % len(projects_info_list))

    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    projects_json_file = os.path.join(backup_dir, "projects.json")

    projects_old_id_to_info = {}
    if os.path.isfile(projects_json_file):
        projects_info_list_old = json.load(open(projects_json_file, mode="r"))
        for item in projects_info_list_old:
            projects_old_id_to_info[item["id"]] = item

    # backup projects
    storage = GitStorage()
    logging.info("Backing up projects..")
    for i, proj in enumerate(projects_info_list):
        proj["url_git"] = "https://git.overleaf.com/%s" % proj["id"]
        proj_git_url = proj["url_git"]
        proj_name = proj["name"]

        # Use project name transformed into valid file/folder name as folder name
        sanitized_proj_name = limit_folder_name_length(get_valid_filename(proj_name))
        proj_backup_path = os.path.join(backup_git_dir, sanitized_proj_name)

        # Handle a potential project name change in OVerleaf
        if proj["id"] in projects_old_id_to_info \
                and (projects_old_id_to_info[proj["id"]]["name"] != proj_name):
            old_proj_name = projects_old_id_to_info[proj["id"]]["name"]
            old_sanitized_proj_name = limit_folder_name_length(get_valid_filename(old_proj_name))
            old_proj_backup_path = os.path.join(backup_git_dir, old_sanitized_proj_name)
            if os.path.isdir(old_proj_backup_path):
                os.rename(old_proj_backup_path, proj_backup_path)
        else:
            old_proj_name = None

        # check if needs backup
        backup = True
        if proj["id"] in projects_old_id_to_info\
                and (projects_old_id_to_info[proj["id"]]["lastUpdated"] >= proj["lastUpdated"])\
                and ("backup_up_to_date" in projects_old_id_to_info[proj["id"]]
                     and projects_old_id_to_info[proj["id"]]["backup_up_to_date"]):
            proj["backup_up_to_date"] = True
            if old_proj_name:
                proj[pushed_to_remote_key] = False  # we need to force a push to change the repo name
            else:
                proj[pushed_to_remote_key] = projects_old_id_to_info[proj["id"]][pushed_to_remote_key]
            backup = False
        else:
            proj["backup_up_to_date"] = False
            proj[pushed_to_remote_key] = False

        if not backup:
            logging.info("{0}/{1} Project {2} with url {3} has not changed since last backup! Skip..."
                         .format(i + 1, len(projects_info_list), sanitized_proj_name, proj_git_url, proj_backup_path))
        else:
            logging.info("{0}/{1} Backing up project {2} with url {3} to {4}"
                         .format(i+1, len(projects_info_list), sanitized_proj_name, proj_git_url, proj_backup_path))

            try:
                storage.create_or_update(proj_git_url, proj_backup_path)
                logging.info("Backup successful!")
                proj["backup_up_to_date"] = True
                proj[pushed_to_remote_key] = False
            except Exception as ex:
                logging.exception("Something went wrong during Overleaf pull!")

        if remote_path and proj["backup_up_to_date"] and not proj[pushed_to_remote_key]:
            try:
                storage.push_to_remote(remote_api_uri, remote_path, remote_name, remote_type, auth_token,
                                       sanitized_proj_name, proj_backup_path,
                                       old_repo_name = old_proj_name, verbose= verbose)
                logging.info("Push successful!")
                proj[pushed_to_remote_key] = True
            except Exception as ex:
                logging.exception("Something went wrong during push to other remote!")

    logging.info("Successfully backed up {} projects out of {}.".format(
        len([proj for proj in projects_info_list if proj["backup_up_to_date"]]),
        len(projects_info_list)))
    if remote_path:
        logging.info("Successfully pushed {} projects out of {} to remote {}.".format(
            len([proj for proj in projects_info_list if proj[pushed_to_remote_key]]),
            len(projects_info_list), remote_name))
    json.dump(projects_info_list, open(projects_json_file, "w"))
    logging.info("Info for {0} projects saved to {1}!".format(len(projects_info_list), projects_json_file))



if __name__ == "__main__":
    main()
