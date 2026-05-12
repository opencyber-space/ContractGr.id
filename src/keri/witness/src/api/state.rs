use std::sync::Arc;

use crate::core::processor::EventProcessor;
use crate::core::watcher_push::WatcherPushService;
use crate::db::repository::WitnessRepository;
use crate::utils::config::Config;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub repo: Arc<dyn WitnessRepository>,
    pub processor: Arc<EventProcessor>,
    pub watcher_push: Arc<WatcherPushService>,
    pub witness_aid: String,
    pub start_time: std::time::Instant,
}

impl AppState {
    pub fn new(
        config: Arc<Config>,
        repo: Arc<dyn WitnessRepository>,
        processor: Arc<EventProcessor>,
        watcher_push: Arc<WatcherPushService>,
    ) -> Self {
        let witness_aid = processor.witness_aid().to_string();
        Self {
            config,
            repo,
            processor,
            watcher_push,
            witness_aid,
            start_time: std::time::Instant::now(),
        }
    }
}