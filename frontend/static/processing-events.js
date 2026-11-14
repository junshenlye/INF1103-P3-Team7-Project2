/** Wake the snapshot poller when durable project events arrive. */
export class ProcessingEvents {
  constructor(projectId) {
    this.wake = null;
    try {
      this.source = new EventSource(
        `/api/projects/${encodeURIComponent(projectId)}/events`,
      );
      this.source.addEventListener('progress', event => {
        try {
          const update = JSON.parse(event.data);
          if (
            ['schedule.updated', 'processing.settled', 'document.completed']
              .includes(update.kind)
          ) {
            this.wake?.();
          }
        } catch {
          // The next snapshot request recovers malformed notifications.
        }
      });
    } catch {
      // Browsers without EventSource retain the timed polling fallback.
    }
  }

  wait(milliseconds) {
    return new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer);
        this.wake = null;
        resolve();
      };
      const timer = setTimeout(finish, milliseconds);
      this.wake = finish;
    });
  }

  close() {
    this.source?.close();
    this.wake?.();
  }
}
