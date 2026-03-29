from csre.worker import celery_app


@celery_app.task(name="csre.rewards.distribute_referral_rewards")
def distribute_referral_rewards(referral_id: str) -> None:
    _ = referral_id
    return None

