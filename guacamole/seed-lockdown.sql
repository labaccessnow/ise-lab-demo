-- Guacamole desktop lockdown for the "Enterprise Lab Desktop" RDP connection.
--
-- The visitor desktop is meant to be pixels-only: you can see and click the real
-- device GUIs, but you cannot move data in or out of the enclave jumpbox. This
-- disables the clipboard (both directions), file transfer (drive + download/upload),
-- audio out, microphone, and printing redirection.
--
-- Idempotent (UPSERT on the connection_id+parameter_name primary key) and keyed by
-- the connection NAME, so it reproduces correctly even if the connection_id differs
-- after a DB rebuild. Apply: docker compose exec -T postgres \
--   psql -U guacamole -d guacamole_db -f - < seed-lockdown.sql
INSERT INTO guacamole_connection_parameter (connection_id, parameter_name, parameter_value)
SELECT c.connection_id, p.name, p.value
FROM guacamole_connection c
CROSS JOIN (VALUES
    ('disable-copy',       'true'),   -- no copy from the remote desktop to the browser
    ('disable-paste',      'true'),   -- no paste from the browser into the remote desktop
    ('enable-drive',       'false'),  -- no RDP filesystem redirection
    ('enable-sftp',        'false'),  -- no SFTP file-transfer channel
    ('disable-download',   'true'),   -- block file download even if a transfer channel exists
    ('disable-upload',     'true'),   -- block file upload even if a transfer channel exists
    ('disable-audio',      'true'),   -- no audio output
    ('enable-audio-input', 'false'),  -- no microphone
    ('enable-printing',    'false')   -- no printer redirection
) AS p(name, value)
WHERE c.connection_name = 'Enterprise Lab Desktop'
ON CONFLICT (connection_id, parameter_name)
DO UPDATE SET parameter_value = EXCLUDED.parameter_value;
