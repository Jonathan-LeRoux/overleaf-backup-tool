import json
import click
import pickle
import re
import csv

from clients.OverleafClient import OverleafClient
from storage.GitStorage import create_or_update_local_backup, push_to_remote
from utils.debug import enable_http_client_debug, is_debug

import os
import logging

MAX_FILENAME_LENGTH = 40


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


def sanitize_name(proj, projects_info_list, projects_old_id_to_info):
    proj_name = proj["name"]
    candidate_name = limit_folder_name_length(get_valid_filename(proj_name), max_length=MAX_FILENAME_LENGTH)
    # Check if there is another project with the same sanitized name, rename if so
    # Look at projects that have just been considered for backup
    # or look at projects that were backed up during a previous backup session and have a different ID
    if [p for p in projects_info_list
        if "backup_up_to_date" in p and p["sanitized_name"] == candidate_name]\
            or [p for p in projects_old_id_to_info.values()
                if p["id"] != proj["id"] and p["sanitized_name"] == candidate_name]:
        if len(candidate_name) > MAX_FILENAME_LENGTH - 4:
            candidate_name = candidate_name[:MAX_FILENAME_LENGTH-4] + proj["id"][-4:]
        else:
            candidate_name = candidate_name + proj["id"][-4:]
    if [p for p in projects_info_list
        if "backup_up_to_date" in p and p["sanitized_name"] == candidate_name] \
            or [p for p in projects_old_id_to_info.values()
                if p["id"] != proj["id"] and p["sanitized_name"] == candidate_name]:
        raise RuntimeError("Project name {} cannot be sanitized without clashing".format(proj_name))
    return candidate_name


@click.command()
@click.option('-c', '--cookie-path', default="", type=click.Path(exists=False),
              help="Relative path to save/load the persisted Overleaf cookie.")
@click.option('-b', '--backup-dir', default="./", type=click.Path(exists=True),
              help="Path of folder in which to store git backups.")
@click.option('-u', '--remote-api-uri', default="", type=str,
              help="Path to remote API if pushing git repos to another remote.")
@click.option('-r', '--remote-path', default="", type=str,
              help="Rhodecode: Path (w/o base URI) to subfolder for pushing git repos to RC remote.\n"
                   "Github: Prefix for names of repos pushed to Github.")
@click.option('-a', '--auth-token', default="", type=str,
              help="Auth token for remote API access for pushing git repos.")
@click.option('-g', '--github-username', default="", type=str,
              help="Github username.")
@click.option('-o', '--github-orgname', default="", type=str,
              help="Name of Github organization under which to store repos "
                   "(leave empty to use repos for the authenticated user).")
@click.option('-n', '--remote-name', default="", type=str,
              help="Name (within git) of remote for pushing git repos to another remote.")
@click.option('-t', '--remote-type', default="rc", type=click.Choice(['rc', 'github'], case_sensitive=False),
              help="Type of other remote for pushing git repos (either 'rc' or 'github').")
@click.option('--include-archived/--ignore-archived', 'include_archived', default=False,
              help="Download archived projects as well (Default: No).")
@click.option('--verbose/--non-verbose', 'verbose', default=False,
              help="Verbose mode (Default: No).")
@click.option('--csv-only/--no-csv-only', default=False,
              help="Only generate CSV without backing up,  (Default: No).")
@click.option('--force-push/--no-force-push', 'force_push', default=False,
              help="Force push to remote (Default: No).")
@click.option('--move-backups-when-possible/--never-move-backups', 'move_backup', default=True,
              help="Move local backup to user-specified location if possible (Default: Yes).")
def main(cookie_path, backup_dir, include_archived, remote_api_uri, remote_path, remote_type,
         remote_name, auth_token, github_username, github_orgname, verbose, force_push, csv_only, move_backup):
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)

    verbose = is_debug() or verbose
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        enable_http_client_debug()  # log http requests

    backup_git_dir = "git_backup/"

    if not backup_dir.endswith("/"):
        backup_dir = backup_dir + "/"

    if remote_type == 'github':
        if not github_username:
            logging.exception("A Github username needs to be specified when pushing to Github.")
            return False
        if not remote_api_uri:
            remote_api_uri = 'https://api.github.com/'
        elif not remote_api_uri.endswith("/"):
            remote_api_uri = remote_api_uri + "/"
        if not remote_path:
            remote_path = 'overleaf-'
        if not remote_name:
            remote_name = 'github'

    if remote_type == 'rc':
        if not remote_api_uri.endswith("/"):
            remote_api_uri = remote_api_uri + "/"
        if not remote_name:
            remote_name = 'rc'

    pushed_to_remote_key = "pushed_to_remote_{}".format(remote_name)
    enable_remote_key = "enable_remote_{}".format(remote_name)
    set_of_enable_remote_keys = {enable_remote_key}

    backup_git_dir = os.path.join(backup_dir, backup_git_dir)

    if not os.path.isfile(cookie_path):
        logging.info("Please log in to overleaf in a browser, then use Web Developer Tools (Ctrl+Shift+I) "
                     "to find the following cookie information.\n"
                     "Look for the overleaf.com cookie under Storage>Cookies (under Application in Chrome).\n"
                     "For GCLB, copy the value string.\n"
                     "For overleaf_session2, copy the 'parsed value' (Firefox) or check 'Show URL decoded' and "
                     "copy the value (Chrome), in both cases starting with 's:...'.")
        GCLB = click.prompt("GCLB")
        overleaf_session2 = click.prompt("overleaf_session2", hide_input=True)
        # Remove GCLB key and double quotes if copied (e.g., in Firefox)
        GCLB = GCLB.strip('GCLB').strip('"')
        overleaf_session2 = 's:' + overleaf_session2.strip("s:").strip('"')  # Handle extra double quotes (e.g., in Firefox)
        cookie = {'GCLB': GCLB,
                  'overleaf_session2': overleaf_session2}
        store = {'cookie': cookie, 'csrf': None}

        overleaf_client = OverleafClient(store["cookie"], store["csrf"])
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
    if not projects_info_list:
        logging.info("No projects to backup, most likely a failed login.")
        return False

    logging.info("Total projects: %s" % len(projects_info_list))

    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    projects_json_file = os.path.join(backup_dir, "projects.json")

    projects_old_id_to_info = {}
    if os.path.isfile(projects_json_file):
        projects_info_list_old = json.load(open(projects_json_file, mode="r"))
        for item in projects_info_list_old:
            projects_old_id_to_info[item["id"]] = item

    projects_csv_file = os.path.join(backup_dir, "projects.csv")
    projects_csv_id_to_info = {}
    if os.path.isfile(projects_csv_file):
        with open(projects_csv_file, mode='r', encoding='utf-8') as csv_file:
            projects_info_list_csv = list(csv.DictReader(csv_file))
        for item in projects_info_list_csv:
            projects_csv_id_to_info[item["id"]] = item
        # add 'enable_remote_' key for all remotes tracked in .csv file to the set of keys that need to be tracked
        if len(projects_info_list_csv) > 0:
            set_of_enable_remote_keys.update([remote_key for remote_key in projects_info_list_csv[0]
                                              if remote_key.startswith('enable_remote_')])
    else:  # if no .csv, just copy the info from json
        projects_csv_id_to_info = projects_old_id_to_info
        for proj_id in projects_csv_id_to_info:
            if "enable_backup" not in projects_csv_id_to_info[proj_id]:
                projects_csv_id_to_info[proj_id]["enable_backup"] = '1'
            if "user_backup_path" not in projects_csv_id_to_info[proj_id]:
                projects_csv_id_to_info[proj_id]["user_backup_path"] = ''
    # This one is outside the condition because for a new remote, the key won't exist in the .csv either
    for proj_id in projects_csv_id_to_info:
        if enable_remote_key not in projects_csv_id_to_info[proj_id]:
            # One issue is that rc being default for remote_type, it will be enabled even if the user doesn't ask for it
            projects_csv_id_to_info[proj_id][enable_remote_key] = '1'

    # backup projects
    logging.info("Backing up projects..")
    for i, proj in enumerate(projects_info_list):
        proj["url_git"] = "https://git.overleaf.com/%s" % proj["id"]
        proj_git_url = proj["url_git"]

        # Use project name transformed into valid file/folder name as folder name,
        # making sure there is no clash with existing shortened names
        sanitized_proj_name = sanitize_name(proj, projects_info_list, projects_old_id_to_info)
        proj_backup_path = os.path.join(backup_git_dir, sanitized_proj_name)
        proj["sanitized_name"] = sanitized_proj_name
        proj["backup_path"] = proj_backup_path  # this is the default, may be overwritten later

        # Let's see if the user specified a backup path; if so, we stick with it
        user_specified_backup_path = False
        user_enable_backup = 1
        proj["user_backup_path"] = ''
        if proj["id"] in projects_csv_id_to_info:
            user_enable_backup = int(projects_csv_id_to_info[proj["id"]]["enable_backup"])
            csv_proj_backup_path = projects_csv_id_to_info[proj["id"]]["user_backup_path"]
            old_proj_backup_path = projects_old_id_to_info[proj["id"]]["backup_path"]
            csv_proj_backup_path = csv_proj_backup_path.strip()
            if csv_proj_backup_path:
                # User specified path other than default
                user_specified_backup_path = True
                proj_backup_path = csv_proj_backup_path
                proj["user_backup_path"] = proj_backup_path
                logging.info("{0}/{1} User specified path {2} for project {3} other than default..."
                             .format(i + 1, len(projects_info_list), csv_proj_backup_path, sanitized_proj_name))
                if not csv_only and csv_proj_backup_path != old_proj_backup_path:
                    # user specified path is different from previous backup path
                    if move_backup and not os.path.isdir(csv_proj_backup_path) \
                            and os.path.isdir(old_proj_backup_path):
                        # if user specified folder does not exist, we try moving the old backup.
                        # we use os.renames here to create intermediate folders if needed...
                        logging.info("{0}/{1} Moving old backup to new user specified path..."
                                     .format(i + 1, len(projects_info_list)))

                        os.renames(old_proj_backup_path, csv_proj_backup_path)
                    else:
                        # user specified path exists, unsafe to overwrite with old backup, force git clone or pull
                        projects_old_id_to_info[proj["id"]]["backup_up_to_date"] = False
                        logging.info("{0}/{1} Specified existing path different from previous path, "
                                     "forcing backup...".format(i + 1, len(projects_info_list)))
                        if os.path.isdir(old_proj_backup_path):
                            logging.info("{0}/{1} Please consider deleting {2}..."
                                         .format(i + 1, len(projects_info_list), old_proj_backup_path))
                else:
                    # Either we are in csv-only mode, or the user-specified path was already used before.
                    # Either way, the current backup path should stay the same as in the json file.
                    proj["backup_path"] = old_proj_backup_path
            elif "user_backup_path" in projects_old_id_to_info[proj["id"]] \
                    and projects_old_id_to_info[proj["id"]]["user_backup_path"] != csv_proj_backup_path:
                # User stopped specifying a backup path
                projects_old_id_to_info[proj["id"]]["backup_up_to_date"] = False
                logging.info("{0}/{1} User no longer specifying non-default path, going back to default, "
                             "forcing backup...".format(i + 1, len(projects_info_list)))
                if os.path.isdir(old_proj_backup_path):
                    logging.info("{0}/{1} Please consider deleting {2}..."
                                 .format(i + 1, len(projects_info_list), old_proj_backup_path))

        proj["enable_backup"] = user_enable_backup
        proj["backup_up_to_date"] = False
        # read info about whether remotes are enabled or not, defaulting to no backup
        for remote_key in set_of_enable_remote_keys:
            if proj["id"] in projects_csv_id_to_info and remote_key in projects_csv_id_to_info[proj["id"]]:
                proj[remote_key] = int(projects_csv_id_to_info[proj["id"]][remote_key])
            else:  # this only applies to projects that were added while another remote was considered
                proj[remote_key] = 0
        proj[pushed_to_remote_key] = False

        if not user_enable_backup:
            if proj[enable_remote_key]:
                logging.info("{0}/{1} User asked to skip local backup but to push to remote for project {2}."
                             "These settings are incompatible, as local backup is needed for remote push."
                             .format(i + 1, len(projects_info_list), sanitized_proj_name))
            # User does not want local backup for this project, skip everything else
            continue

        # Handle a potential project name change in Overleaf
        if proj["id"] in projects_old_id_to_info \
                and (projects_old_id_to_info[proj["id"]]["sanitized_name"] != sanitized_proj_name):
            # specifying old_sanitized_proj_name will force an update in the remote
            old_sanitized_proj_name = projects_old_id_to_info[proj["id"]]["sanitized_name"]
            old_proj_backup_path = projects_old_id_to_info[proj["id"]]["backup_path"]
            # only change local folder name if not specified by user
            if not user_specified_backup_path:
                if os.path.isdir(old_proj_backup_path):
                    logging.info("{0}/{1} Project {2} has changed name from {4} since last backup, "
                                 "renaming local folder... (Overleaf url: {3})"
                                 .format(i + 1, len(projects_info_list), sanitized_proj_name, proj_git_url,
                                         old_sanitized_proj_name))
                    os.rename(old_proj_backup_path, proj_backup_path)
                else:
                    # There should really be a folder, so if there is none, let's assume we need to backup
                    projects_old_id_to_info[proj["id"]]["backup_up_to_date"] = False
                    logging.info("{0}/{1} Couldn't find previous local backup folder {2} for project {3}, "
                                 "redownloading to folder {4}..."
                                 .format(i + 1, len(projects_info_list), old_proj_backup_path, sanitized_proj_name,
                                         proj_backup_path))
        else:
            old_sanitized_proj_name = None

        # check if needs backup
        backup = True
        if proj["id"] in projects_old_id_to_info \
                and (projects_old_id_to_info[proj["id"]]["lastUpdated"] >= proj["lastUpdated"]) \
                and ("backup_up_to_date" in projects_old_id_to_info[proj["id"]]
                     and projects_old_id_to_info[proj["id"]]["backup_up_to_date"]):
            proj["backup_up_to_date"] = True
            if pushed_to_remote_key not in projects_old_id_to_info[proj["id"]]:  
                # this is a new remote, we add it to old info for convenience as proj will inherit all old info
                projects_old_id_to_info[proj["id"]][pushed_to_remote_key] = False
            if old_sanitized_proj_name:  
                # we need to force a push to change the repo name on all remotes (next time each remote is updated)
                projects_old_id_to_info[proj["id"]].update({remote_key: False
                                                            for remote_key in projects_old_id_to_info[proj["id"]]
                                                            if remote_key.startswith('pushed_to_remote')})
            # Now copy info for all remotes
            proj.update({remote_key: value
                         for (remote_key, value) in projects_old_id_to_info[proj["id"]].items()
                         if remote_key.startswith('pushed_to_remote')})
            backup = False

        if not csv_only:
            if not backup:
                logging.info("{0}/{1} Project {2} unchanged since last backup! Skip... (Overleaf url: {3})"
                             .format(i + 1, len(projects_info_list), sanitized_proj_name, proj_git_url))
            else:
                logging.info("{0}/{1} Backing up project {2} to {4}  (Overleaf url: {3})"
                             .format(i+1, len(projects_info_list), sanitized_proj_name, proj_git_url, proj_backup_path))

                try:
                    create_or_update_local_backup(proj_git_url, proj_backup_path)
                    logging.info("Backup successful!")
                    proj["backup_up_to_date"] = True
                    # All remotes will need to be updated
                    proj.update({remote_key: False for remote_key in proj
                                 if remote_key.startswith('pushed_to_remote')})
                    # in case backup path was not default, we update it here now that backup did succeed
                    proj["backup_path"] = proj_backup_path
                except RuntimeError:
                    logging.exception("Something went wrong during Overleaf pull, moving on!")

            if remote_type and proj[enable_remote_key] \
                    and proj["backup_up_to_date"] and (not proj[pushed_to_remote_key] or force_push):
                try:
                    push_to_remote(remote_api_uri, remote_path, remote_name, remote_type, auth_token,
                                   sanitized_proj_name, proj_backup_path,
                                   old_repo_name=old_sanitized_proj_name,
                                   github_username=github_username,
                                   github_orgname=github_orgname,
                                   verbose=verbose)
                    logging.info("Push successful!")
                    proj[pushed_to_remote_key] = True
                except (RuntimeError, OSError):
                    logging.exception("Something went wrong during push to other remote, moving on!")

    if not csv_only:
        logging.info("Successfully backed up {} projects out of {}.".format(
            len([proj for proj in projects_info_list if proj["backup_up_to_date"]]),
            len(projects_info_list)))
        if remote_type:
            logging.info("Successfully pushed {} projects out of {} to remote {}.".format(
                len([proj for proj in projects_info_list if proj[pushed_to_remote_key]]),
                len(projects_info_list), remote_name))
    json.dump(projects_info_list, open(projects_json_file, "w"))
    logging.info("Info for {0} projects saved to {1}!".format(len(projects_info_list), projects_json_file))

    with open(projects_csv_file, mode='w', newline='', encoding='utf-8') as csv_file:
        fieldnames = ["id", "sanitized_name", "enable_backup", "user_backup_path"] + sorted(set_of_enable_remote_keys)
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for proj in sorted(projects_info_list, key=lambda k: k['sanitized_name']):
            proj['sanitized_name'] = proj['sanitized_name'].ljust(MAX_FILENAME_LENGTH)
            writer.writerow({k: proj.get(k, "") for k in fieldnames})


if __name__ == "__main__":
    main()
