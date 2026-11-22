"""One planned maintenance cycle: stop, cold backup, verify, restart (even after backup failure)."""
import argparse,datetime,pathlib
import manage

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',default='workhub-server',type=manage.project_name)
    p.add_argument('--destination',default=str(manage.ROOT/'artifacts'))
    a=p.parse_args()
    if not manage.status(a.project,quiet=True)['ok']:
        raise RuntimeError('Expected a running healthy project. For an already stopped project use manage.py backup.')
    dest=pathlib.Path(a.destination).resolve()/('backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    try:
        manage.compose(a.project,'stop','--timeout','45')
        manage.backup(a.project,dest)
        manage.verify_backup(dest)
    finally:
        # Do not leave the service stopped just because a backup failed.
        manage.start(a.project)
    print('Backup verified and service restarted:',dest)

if __name__=='__main__':main()
