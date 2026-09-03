from datetime import UTC, datetime

from tandemn_system_data.models.gpu_metric import (
    GpuMetric,
    gpu_metric_from_row,
    gpu_metric_to_metrics,
)


def test_batch_metrics_round_trip_through_metrics_json():
    ts = datetime(2026, 9, 1, tzinfo=UTC)
    metric = GpuMetric(
        metric_id="metric_1",
        ts=ts,
        job_id="job_1",
        gpu_uuid="GPU-1",
        batched_reqs_inflight=100.0,
        batched_reqs_processed_total=387.0,
        batched_chunks_input_pulled_total=7.0,
        batched_chunks_output_written_total=2.0,
    )

    metrics = gpu_metric_to_metrics(metric)
    rebuilt = gpu_metric_from_row(
        metric_id=metric.metric_id,
        ts=ts,
        job_id=metric.job_id,
        gpu_uuid=metric.gpu_uuid,
        rank_id=None,
        chain_index=None,
        local_rank=None,
        role=None,
        node_name=None,
        instance_type=None,
        model_name=None,
        metrics=metrics,
    )

    assert rebuilt.batched_reqs_inflight == 100.0
    assert rebuilt.batched_reqs_processed_total == 387.0
    assert rebuilt.batched_chunks_input_pulled_total == 7.0
    assert rebuilt.batched_chunks_output_written_total == 2.0
