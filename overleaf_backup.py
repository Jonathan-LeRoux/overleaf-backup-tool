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

def limit_folder_name_length(folder_name, max_length=30):
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
@click.option('--cookie-path', default=".olauth", type=click.Path(exists=False),
              help="Relative path to save/load the persisted Overleaf cookie.")
@click.option('-b', '--backup-dir', default="./", type=click.Path(exists=True),
              help="Path of folder in which to store git backups.")
@click.option('--include-archived/--ignore-archived', 'include_archived', default=False,
              help="Download archived projects as well (Default: No).")
def main(cookie_path, backup_dir, include_archived):
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)

    if is_debug():
        logging.getLogger().setLevel(logging.DEBUG)
        enable_http_client_debug()  # log http requests

    backup_git_dir = "git_backup/"

    if not backup_dir.endswith("/"):
        backup_dir = backup_dir + "/"

    backup_git_dir = os.path.join(backup_dir, backup_git_dir)

    if not os.path.isfile(cookie_path):
        username = click.prompt("Username")
        password = click.prompt("Password", hide_input=True)
        overleaf_client = OverleafClient()
        store = overleaf_client.login_with_user_and_pass(username, password)
        if store is None:
            return False
        with open(cookie_path, 'wb+') as f:
            pickle.dump(store, f)
    else:
        logging.info("Using stored credentials, please delete {} if you would like to login again".format(cookie_path))
        with open(cookie_path, 'rb') as f:
            store = pickle.load(f)

        overleaf_client = OverleafClient(store["cookie"], store["csrf"])

    projects_info_list = overleaf_client.all_projects(include_archived=include_archived)
    # projects_info_list = overleaf_client.get_projects(status="all")

    logging.info("Total projects:%s" % len(projects_info_list))

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
        proj_id = proj["id"]
        proj_git_url = proj["url_git"]
        proj_name = proj["name"]

        # Use project name transformed into valid file/folder name as folder name
        proj_backup_path = os.path.join(backup_git_dir, limit_folder_name_length(get_valid_filename(proj_name)))

        # check if needs backup
        backup = True
        if proj["id"] in projects_old_id_to_info\
                and (projects_old_id_to_info[proj["id"]]["lastUpdated"] >= proj["lastUpdated"])\
                and ("backup_up_to_date" in projects_old_id_to_info[proj["id"]]
                     and projects_old_id_to_info[proj["id"]]["backup_up_to_date"]):
            proj["backup_up_to_date"] = True
            backup = False
        else:
            proj["backup_up_to_date"] = False

        if not backup:
            logging.info("{0}/{1} Project {2} with url {3} has not changed since last backup! Skip..."
                         .format(i + 1, len(projects_info_list), proj_id, proj_git_url, proj_backup_path))
            continue

        logging.info("{0}/{1} Backing up project {2} with url {3} to {4}"
                     .format(i+1, len(projects_info_list), proj_id, proj_git_url, proj_backup_path))

        try:
            storage.create_or_update(proj_git_url, proj_backup_path)
            logging.info("Backup successful!")
            proj["backup_up_to_date"] = True
        except Exception as ex:
            logging.exception("Something went wrong!")

    logging.info("Successfully backed up {} projects out of {}.".format(
        len([proj for proj in projects_info_list if proj["backup_up_to_date"]]), len(projects_info_list)))
    json.dump(projects_info_list, open(projects_json_file, "w"))
    logging.info("Info for {0} projects saved to {1}!".format(len(projects_info_list), projects_json_file))



if __name__ == "__main__":
    main()
