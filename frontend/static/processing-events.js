/** A notification stream with timed GET fallback; it never owns backend work. */
export class ProcessingEvents {
  constructor(projectId) {
    this.wake = null;
    try {
      this.source = new EventSource(`/api/projects/${encodeURIComponent(projectId)}/events`);
      this.source.addEventListener('progress', event => {
        try {
          const update = JSON.parse(event.data);
          if (['schedule.updated', 'processing.settled', 'document.completed'].includes(update.kind)) this.wake?.();
        } catch { /* The next snapshot GET recovers malformed notifications. */ }
      });
    } catch { /* Polling remains available when streaming is unsupported. */ }
  }
  wait(milliseconds) {
    return new Promise(resolve => {
      const finish = () => { clearTimeout(timer); this.wake = null; resolve(); };
      const timer = setTimeout(finish, milliseconds);
      this.wake = finish;
    });
  }
  close() { this.source?.close(); this.wake?.(); }
}
