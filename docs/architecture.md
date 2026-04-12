# Architecture Overview

```
Flutter App  <-->  FastAPI Backend  <-->  PostgreSQL / Redis
                        |
              +---------+---------+
              |                   |
        Canvas API       Google Calendar API
              |                   |
              +---------+---------+
                        |
                   ML Module
              (task estimator,
               schedule optimizer,
               intent parser)
```

## Data Flow

1. User authenticates via Google OAuth
2. Backend syncs Canvas assignments and Google Calendar events
3. ML scheduler suggests flexible study blocks
4. Flutter app displays unified calendar view
5. User sends chat message -> intent parser -> schedule action -> UI update
