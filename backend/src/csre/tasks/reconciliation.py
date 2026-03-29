from csre.worker import celery_app


@celery_app.task(name="csre.reconciliation.detect_graph_divergence")
def detect_graph_divergence() -> None:
    return None

