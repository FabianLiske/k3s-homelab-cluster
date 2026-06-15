# Immich Backup

This directory defines the Kubernetes backup job for the local Immich data on the media node.

The NAS NFS export is mounted at `/mnt/tank/backups/immich` from `172.26.60.223`. The job creates all directories below that export automatically.

## Schedule

The CronJob runs twice per day in the `Europe/Berlin` timezone:

- `03:15`
- `15:15`

`concurrencyPolicy: Forbid` prevents a second backup run from starting while a previous run is still active.

## Scope

The job backs up Immich data that lives on local `media-local` PVs:

- `immich-library-data`: `/srv/media-hdd/immich/library`
- `immich-generated-data`: `/data/immich/generated`
- `immich-model-cache-data`: `/data/immich/model-cache`

The Postgres data directory at `/data/immich/postgres` is not copied raw. Instead, the job creates a logical `pg_dump` before syncing files, which matches Immich's recommended ordering: database first, filesystem second.

Reference: https://docs.immich.app/administration/backup-and-restore/

## NAS Layout

The job writes this layout below `/mnt/tank/backups/immich`:

```text
current/
  upload-location/
    backups/
    encoded-video/
    library/
    profile/
    thumbs/
    upload/
  model-cache/
database/
  immich-YYYYMMDDTHHMMSSZ.sql.gz
rsync-deleted/
  YYYYMMDDTHHMMSSZ/
    upload-location/
    model-cache/
```

`current/upload-location` is the restore-friendly mirror of Immich's `/data` upload location. It combines the split Kubernetes PVC layout back into the folder shape Immich expects during restore.

`database` keeps logical database dumps for 45 days.

`rsync-deleted` keeps files replaced or deleted during rsync runs for 45 days, so accidental deletions are not immediately lost from the NAS mirror.

## Restore Notes

For a fresh Immich restore, prefer Immich's web/onboarding restore flow when possible:

1. Restore `current/upload-location` so the new Immich `UPLOAD_LOCATION` contains the expected `backups`, `encoded-video`, `library`, `profile`, `thumbs`, and `upload` directories.
2. Start Immich and choose a database backup from `UPLOAD_LOCATION/backups` or upload one from `database/`.

For this cluster's split PVC layout, restore files back to the media node paths like this:

- Copy `current/upload-location/` to `/srv/media-hdd/immich/library/`, excluding `backups`, `encoded-video`, `profile`, and `thumbs`.
- Copy `current/upload-location/backups` to `/data/immich/generated/backups`.
- Copy `current/upload-location/encoded-video` to `/data/immich/generated/encoded-video`.
- Copy `current/upload-location/profile` to `/data/immich/generated/profile`.
- Copy `current/upload-location/thumbs` to `/data/immich/generated/thumbs`.
- Optionally copy `current/model-cache/` to `/data/immich/model-cache/`; Immich can regenerate model cache data.

For command-line database restore, use one of the `database/immich-*.sql.gz` dumps against a fresh Immich database. Do not restore by copying `/data/immich/postgres` from a live backup.
