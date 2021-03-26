# Overleaf backup tool
Tool for backing up projects from Overleaf, forked from https://github.com/tbmihailov/overleaf-backup-tool.

Main changes from original repo:
- Imported code from https://github.com/moritzgloeckl/overleaf-sync 
to handle Overleaf v2 and securely input password without having 
to write it on the command line (using Click). 
- Replaced project ID with a sanitized version of the project name 
as folder name.
- Reduced wait time during retry to 5 s
- Print number of successful backups
- Optionally push backed up repo to remote on a Rhodecode server, 
creating it if it doesn't exist; requires creating an API auth_token on Rhodecode
 (Note: I may add Github support later)

## Installation
Works with Python 3.+

```bash
git clone https://github.com/Jonathan-LeRoux/overleaf-backup-tool.git
cd overleaf-backup-tool
pip install -r requirements.txt
```

## Usage
```bash
python overleaf_backup.py --backup_dir my_backup_dir --include-archived
# The code will try to push to a remote repo if a non-empty string is passed after --remote_path:
python overleaf_backup.py --backup_dir my_backup_dir --include-archived --remote-api-uri remote_api_uri --remote-path path/to/folder/on/remote/server -auth-token your_auth_token --remote-type rc
```

## How it works
The tool logs in with your Overleaf username and password and downloads 
all non-archived projects (and optionally archived as well) via git.

The first time, you will be prompted for username and password, but after login 
has been successful once, the saved cookie information will be used instead.

You will find the cloned projects folders in backup_dir/git_backup/:

```text
your_backup_dir/
└── git_backup
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
   ├── projects.json
```

projects.json contains the metadata about the projects in Overleaf.
Successfully backed up projects will not be downloaded again if they are not changed in Overleaf.
