"""Local visit email worker. No scheduler is installed or enabled by this file."""
import os
import argparse
from run_followup_worker import load_config
from visit_journey import run_visit_worker, schema
from followup_service import email_config_issues, _connect, FOLLOWUP_DB


def main(argv=None, _attempt=0):
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
        # CRM discovery is independent of whether any messages are due.
        from visit_journey import owner_journeys
        from crm_service import sync_visits
        if str(config.get('VISIT_EMAIL_ENABLED','false')).lower()=='true':
            sync_visits(owner_journeys())
        sent,failed=run_visit_worker(config)
        from purchase_confirmation import run_purchase_worker
        purchase_sent,purchase_failed=run_purchase_worker(config)
        sent+=purchase_sent;failed+=purchase_failed
        print(f'Visit emails: {sent} submitted, {failed} need review. SMTP acceptance is not delivery confirmation.')
        return 1 if failed else 0
    except Exception as error:
        if getattr(error,'sqlstate',None)=='40P01' and _attempt<2:
            print('Database deadlock rolled back; retrying safely from saved email states.')
            return main(argv, _attempt+1)
        print('Visit worker stopped: '+type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
