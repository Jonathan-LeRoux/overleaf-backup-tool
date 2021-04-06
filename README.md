# Overleaf backup tool
Tool for backing up projects from Overleaf, forked from https://github.com/tbmihailov/overleaf-backup-tool.

Main changes from original repo:
- Imported code from https://github.com/moritzgloeckl/overleaf-sync 
to handle Overleaf v2 and securely input password without having 
to write it on the command line (using Click). 
- Replaced project ID with a sanitized and shortened version of the project name 
as folder name, handling clashes between identical shortened version by adding 
last 4 characters of project ID.
- Creates CSV file with list of repos, letting the user specify for each repo 
whether to perform local backup, a non-default location for the local backup,
  and whether to perform remote backup.
- Added "CSV only" mode that only reads information from Overleaf and creates 
CSV file, so that user can tune behavior for each repo prior to first actual backup.
- Optionally push backed up repo to remote(s) on a Rhodecode server, 
creating the remote repo if it doesn't exist; 
  - requires creating an API auth_token on Rhodecode 
  - multiple remotes can be used by re-running the code with different remote parameters
  - Note: repo group (folder in which Overleaf repos will be backed up) needs to be manually created as of now.
  - Help welcome: I would like to add Github support down the road, 
  but handling hierarchies may not be as easy as with RC. Otherwise, it "should" just be a matter of 
  making the right API call. I envision adding "overleaf-" in front of each project name for clarity in Github.
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
```bash
# First run to create CSV file that allows tweaking preferences for each repo
python overleaf_backup.py --backup-dir my_backup_dir --include-archived --csv-only
# The code will try to push to a remote repo if a non-empty string is passed after --remote_path:
python overleaf_backup.py --backup-dir my_backup_dir --include-archived --remote-api-uri remote_api_uri --remote-path path/to/folder/on/remote/server --auth-token your_auth_token --remote-type rc --remote-name rc --cookie-path .olauth --verbose
```

## How it works
The tool logs in with your Overleaf username and password and downloads 
all non-archived projects (and optionally archived as well) via git.

The first time, you will be prompted for username and password, but 
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

projects.json contains the metadata about the projects in Overleaf.

projects.csv contains user settings on whether to perform local and/or remote backup, 
and which location to use for local backup.

Successfully backed up projects will not be downloaded again if they are not changed in Overleaf.

If the Overleaf project name changes and default backup location is used, backup folder will be renamed accordingly.
If a user-specified location is used, it will remain as is.

## Setting preferences for each repo
projects.csv allows the user to set preferences for each repo, via the last 3 columns of each row:
- perform local backup or not: 1 to backup, 0 to skip; 0 will skip both local and remote
- choose non-default location for local backup: replace empty string with non-default backup path as needed. 
The specified backup folder needs to be either empty, non-existent, or a folder already
 containing the corresponding Overleaf git repo. 
 *Full path needs to be specified, and the project name will NOT be added.*
- perform remote backup or not (1 to backup, 0 to skip; needs local backup to be set to 1, 
as local backup is needed for push to remote)

```csv
a1c1e1g1i1k1m1o1q1s1u1w1,My_Project_a,1,,1
a2c2e2g2i2k2m2o2q2s2u2w2,My_Project_b,1,~/articles/GreatConf/2021/Paper1/,1
a3c3e3g3i3k3m3o3q3s3u3w3,My_Project_c,1,,1
```