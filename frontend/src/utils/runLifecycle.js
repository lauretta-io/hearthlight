export const RUN_STARTED_EVENT = 'hearthlight:run-started';
export const SOURCES_UPDATED_EVENT = 'hearthlight:sources-updated';

export const dispatchRunStarted = (runId) => {
  window.dispatchEvent(new CustomEvent(RUN_STARTED_EVENT, {
    detail: { run_id: runId ?? null },
  }));
};

export const applyOptimisticRunOverview = (overview, runId) => {
  if (!overview) {
    return {
      generated_at: new Date().toISOString(),
      system_status: 'initializing',
      current_run_id: runId ?? null,
      sources: [],
      runs: [],
      resources: {},
    };
  }
  return {
    ...overview,
    system_status: 'initializing',
    current_run_id: runId ?? overview.current_run_id,
    sources: (overview.sources || []).map((source) => (
      source.enabled ? { ...source, state: 'initializing' } : source
    )),
  };
};
