"""Local visit email worker. No scheduler is installed or enabled by this file."""
import os
from run_followup_worker import load_config
from visit_journey import run_visit_worker


if __name__ == '__main__':
    config=load_config()
    # Only an explicit worker environment flag enables delivery. Website secrets
    # and the existing daily follow-up task do not enable this new worker.
    config['VISIT_EMAIL_ENABLED']=os.environ.get('VISIT_EMAIL_ENABLED','false')
    if config.get('DATABASE_URL'):
        os.environ['DATABASE_URL']=config['DATABASE_URL']
    try:
        sent,failed=run_visit_worker(config)
        print(f'Visit emails: {sent} submitted, {failed} need review. SMTP acceptance is not delivery confirmation.')
        raise SystemExit(1 if failed else 0)
    except Exception as error:
        print('Visit worker stopped: '+type(error).__name__)
        raise SystemExit(1)
