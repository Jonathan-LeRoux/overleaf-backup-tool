# Overleaf backup tool
Tool for backing up projects from Overleaf

This code was originally forked from https://github.com/tbmihailov/overleaf-backup-tool, 
but it has since evolved significantly, in particular to include the ability to
automatically push to another remote such as a Rhodecode server or Github, and to let
the user specify local backup locations for each project.

### This is a *backup* tool, not a *sync* tool. 

If the user makes any changes locally (or on the optional remote), these changes 
will not be synced back to overleaf, and in fact the code will most likely "break", 
in that it will fail to backup and skip the corresponding project.

It is possible to edit locally a project (e.g., to work offline), but the changes
will need to be synced back to Overleaf by manually commiting and pushing them using
 git, outside of this tool. The next backup will then work properly.
 
Handling commits, merges, etc, is outside the scope of this repo, and it is unlikely
that I will consider adding it.

### Main changes from original repo

- Imported code from https://github.com/moritzgloeckl/overleaf-sync 
to handle Overleaf v2.
- Replaced username/password login with login based on cookie information to be
 be retrieved after logging in with a browser. 
- Replaced project ID with a sanitized and shortened version of the project name 
as folder name, handling clashes between identical shortened version by adding 
last 4 characters of project ID.
- Added creation of human-readable CSV file with list of repos, 
letting the user specify for each repo:
  - whether to perform local backup, 
  - a non-default location for the local backup,
  - whether to perform remote backup.
- Added "CSV only" mode that only reads information from Overleaf and creates 
CSV file, so that user can tweak the behavior for each repo prior to first actual backup.
- Optionally push backed up repo to remote(s) on a Rhodecode server or Github, 
creating the remote repo if it doesn't exist; 
  - requires creating an auth token with "API calls" permission on Rhodecode, 
  and "repo" permission on Github.  
  - multiple remotes can be used by re-running the code with different remote parameters
  - Note: for Rhodecode, the repo group (folder in which Overleaf repos will be backed up) 
  needs to be manually created as of now. 
  Repo groups are not supported on Github (there is no hierarchy).
- Handle project name changes on Overleaf (rename local folder, and remote repos if needed)
- Reduced wait time during retry to 2 s
- Print number of successful backups

## Installation
Works with Python 3.+

```bash
git clone https://github.com/Jonathan-LeRoux/overleaf-backup-tool.git
cd overleaf-backup-tool
pip install -r requirements.txt
```

## Usage

### Logging in for the first time

First log in to Overleaf with a browser and use Web Developer Tools (`Option/Ctrl+Shift+I` in Firefox and Chrome) 
to retrieve the authentication cookie information.
Look for the overleaf.com cookie under Storage>Cookies (under Application in Chrome).  
The first time you use overleaf_backup, you will be ask for the values of `GCLB` and `overleaf_session2`.
For `GCLB`, copy the value string. For `overleaf_session2`, copy the 'parsed value' (Firefox) or check 'Show URL decoded' and 
copy the value (Chrome), in both cases starting with 's:...'


### Retrieve project information to allow non-default behavior (Optional)  
Unless you are happy with the default behavior (backup all projects in subfolders of a unique folder),
first run in "CSV only" mode to create a CSV file that allows tweaking preferences for each repo:
```bash
python overleaf_backup.py --backup-dir my_backup_dir --csv-only
```
You can now edit the CSV file (see [below](#setting-preferences-for-each-repo)) to choose
whether to backup or not each project, and specify a non-default backup location.

If `--remote-type github` or `--remote-type rc` is further added (defaults to `rc` if the option is not specified),
the CSV file will contain a column to allow choosing whether to push each project to a Github or Rhodecode remote.

### Local backup
To perform local backup only:
```bash
python overleaf_backup.py -b my_backup_dir --verbose
```
### Login without prompt for cookie information
To avoid having to input your cookie information every time, specify a path to save/load the authentication cookie 
whenever using the script:
```bash
python overleaf_backup.py -b my_backup_dir --cookie-path .olauth --verbose
```
### Backup to another remote (Rhodecode, Github)
#### Rhodecode
To push each repo (or a subset of selected ones) to a Rhodecode server, specify the remote_api_uri (after `--remote-api-uri`), 
a path to the folder on the remote server in which all repos will be saved (after `--remote_path`), 
the remote type as `rc` (after `--remote-type`), the name (within git) of the remote (e.g., `rc`, `rhodecode`,
 `myserver`, etc; Overleaf is `origin` by default), and
a Personal Authorization Token with "API call" permission (after `--auth-token`):
```bash
python overleaf_backup.py -b my_backup_dir -u remote_api_uri -r path/to/folder/on/remote/server -a your_auth_token -t rc -n rc -c .olauth --verbose
```
#### Github
To push each repo (or a subset of selected ones) to Github, specify the remote type as `github` (after `--remote-type`), 
a prefix for each repository name (defaults to "overleaf-" if not specified; after `--remote-path`),
a name (within git) for the remote (e.g., `github`; Overleaf is `origin` by default),
a Github username (after `--github-username`)
and a Personal Authorization Token with "repo" permission (after `--auth-token`):
```bash
python overleaf_backup.py -b my_backup_dir -r overleaf- -a your_auth_token -t github -n github -c .olauth --verbose
```
There is no hierarchy on Github, so `--remote_path` can be used instead to specify a prefix to each repository name 
instead of a path. If not specified, the prefix defaults to `overleaf-`.

By default, repos will be created for the authenticated user (i.e., under their account). 
If a Github organization name is specified (after `--github-orgname`), then repos will be created in 
the specified organization instead (assuming the user is a member, of course).

**Note:** Repos are set as private. Because Overleaf commits will most likely contain your private email
address (or certainly not your Github public profile email), you will need to disable the Github option to 
["Block command line pushes that expose my 
email"](https://docs.github.com/en/github/setting-up-and-managing-your-github-user-account/managing-email-preferences/blocking-command-line-pushes-that-expose-your-personal-email-address) 
while you use this tool, or Github will reject the push.
 
##### Github vs Github Enterprise: 
If the remote_api_uri is not specified, github.com is implied and the endpoint is automatically set to 
`https://api.github.com/`.

if you are using Github Enterprise, you will need to specify the remote_api_uri 
(after `--remote-api-uri`) as `https://[YOUR_HOST]/api/v3/`
(Warning: not tested, as I do not have access to a test site).

#### Auth tokens
You will need to create auth tokens with proper permissions: "API calls" for Rhodecode, "repo" for Github.

More details: [Github Auth Tokens](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token), 
[Rhodecode Auth Tokens](https://docs.rhodecode.com/RhodeCode-Enterprise/auth/token-auth.html).

**Warning**: Treat your tokens like passwords and keep them secret. Use tokens as environment 
variables instead of directly writing them on the command line.  

### Full list of options:
```bash
Usage: overleaf_backup.py [OPTIONS]

Options:
  -c, --cookie-path PATH          Relative path to save/load the persisted
                                  Overleaf cookie.
  -b, --backup-dir PATH           Path of folder in which to store git
                                  backups.
  -u, --remote-api-uri TEXT       Path to remote API if pushing git repos to
                                  another remote.
  -r, --remote-path TEXT          Rhodecode: Path (w/o base URI) to subfolder
                                  for pushing git repos to RC remote.
                                  Github:
                                  Prefix for names of repos pushed to Github.
  -a, --auth-token TEXT           Auth token for remote API access for pushing
                                  git repos.
  -g, --github-username TEXT      Github username.
  -o, --github-orgname TEXT       Name of Github organization under which to
                                  store repos (leave empty to use repos for
                                  the authenticated user).
  -n, --remote-name TEXT          Name (within git) of remote for pushing git
                                  repos to another remote.
  -t, --remote-type [rc|github]   Type of other remote for pushing git repos
                                  (either 'rc' or 'github').
  --include-archived / --ignore-archived
                                  Download archived projects as well (Default:
                                  No).
  --verbose / --non-verbose       Verbose mode (Default: No).
  --csv-only / --no-csv-only      Only generate CSV without backing up,
                                  (Default: No).
  --force-push / --no-force-push  Force push to remote (Default: No).
  --move-backups-when-possible / --never-move-backups
                                  Move local backup to user-specified location
                                  if possible (Default: Yes).
  --help                          Show this message and exit.
```

## How it works
The tool logs in to Overleaf and downloads 
all non-archived projects (and optionally archived as well) via git.

The first time, you will be prompted for your cookie information. 
Because Overleaf recently implemented Captcha at login, we can no longer simply use 
username and password in the command line. 
Some [other projects](https://github.com/moritzgloeckl/overleaf-sync/issues/28#) use PyQt to launch a mini
browser, but we found it simpler to just have the user log into Overleaf with a browser and copy the cookie
information. 
if a cookie path is provided, the cookie will be saved and after login 
has been successful once, the saved cookie information will be used instead.

By default, you will find the cloned projects folders in my_backup_dir/git_backup/:
```text
my_backup_dir/
└── git_backup
   ├── projects.csv
   ├── projects.json
   ├── yourproject1name
   │   ├── acl2018.bib
   │   ├── acl2018.sty
   │   ├── acl_natbib.bst
   │   ├── main.tex
   └── yourproject2name
   │   ├── acl2018.bib
   │   ├── acl2018.sty
   │   ├── acl_natbib.bst
   │   ├── main.tex
```

`projects.json` contains the metadata about the projects in Overleaf.

`projects.csv` contains user settings on whether to perform local and/or remote backup, 
and which (non-default) location to use for local backup.

Successfully backed up projects will not be downloaded again if they are not changed in Overleaf.

If the Overleaf project name changes and default backup location is used, backup folder will be renamed accordingly.
If a user-specified location is used, it will remain as is.

It is possible to backup to multiple Rhodecode/Github remotes, 
or to different repo groups on the same Rhodecode remotes, 
by re-running the code with different remote parameters. 
The code will **not** attempt to rename or remove repos created 
with previous parameters, so you will need to clean up yourself
if your intention is to change the remote backup location for good.

## Setting preferences for each repo
`projects.csv` allows the user to set preferences for each repo, via the last columns of each row:
- perform local backup or not (`enable_backup`): 1 to backup, 0 to skip; 0 will skip both local and remote backup.
- choose non-default location for local backup (`user_backup_path`): replace empty string with non-default backup path as needed. 
The specified backup folder needs to be either empty, non-existent, or a folder already
 containing the corresponding Overleaf git repo.  
 *Full path needs to be specified, and the project name will NOT be added, to allow for user customization*, 
 i.e., `C:\Users\username\Documents\Articles\GreatConf\2020\Paper1\` on Windows or `~/Articles/GreatConf/2020/Paper1/`
 on Linux/Mac.
- perform remote backup or not (`enable_remote<remote_name>`, e.g., `enable_remote_github`, `enable_remote_rc`): 
1 to backup, 0 to skip; needs local backup to be set to 1, 
as local backup is needed for push to remote.

Using a setting as the one below:
```csv
id,sanitized_name,enable_backup,user_backup_path,enable_remote_github
a1c1e1g1i1k1m1o1q1s1u1w1,My_Project_a,0,,1
a2c2e2g2i2k2m2o2q2s2u2w2,My_Project_b,1,~/articles/GreatConf/2021/Paper1/,1
a3c3e3g3i3k3m3o3q3s3u3w3,My_Project_c,1,,0
```
`My_Project_a` will be entirely skipped, `My_Project_b`
will be backed up to non-default folder `~/articles/GreatConf/2021/Paper1/` and pushed to Github,
and `My_Project_c` will be backed up locally to the corresponding default location but not further pushed to a remote.