"""Local visit email worker. No scheduler is installed or enabled by this file."""
import os
import argparse
from run_followup_worker import load_config
from visit_journey import run_visit_worker, schema
from followup_service import email_config_issues, _connect, FOLLOWUP_DB


def main(argv=None):
    parser=argparse.ArgumentParser(description='Process consented visit reminder and review emails.')
    parser.add_argument('--check',action='store_true',help='Validate settings without connecting or sending.')
    parser.add_argument('--prepare-storage',action='store_true',help='Prepare shared visit tables without sending messages.')
    args=parser.parse_args(argv)
    config=load_config()
    # Only an explicit worker environment flag enables delivery. Website secrets
    # and the existing daily follow-up task do not enable this new worker.
    config['VISIT_EMAIL_ENABLED']=os.environ.get('VISIT_EMAIL_ENABLED','false')
    if config.get('DATABASE_URL'):
        os.environ['DATABASE_URL']=config['DATABASE_URL']
    try:
        issues=email_config_issues(config)
        if not config.get('DATABASE_URL'):
            issues.append('Shared DATABASE_URL is required for the production visit worker.')
        if issues:
            for issue in issues: print(issue)
            return 2
        if args.prepare_storage:
            with _connect(FOLLOWUP_DB) as connection: schema(connection)
            print('Shared visit storage is ready. No messages sent.')
            return 0
        if args.check:
            print('Visit worker settings are complete. No connection or messages attempted.')
            return 0
        sent,failed=run_visit_worker(config)
        print(f'Visit emails: {sent} submitted, {failed} need review. SMTP acceptance is not delivery confirmation.')
        return 1 if failed else 0
    except Exception as error:
        print('Visit worker stopped: '+type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
