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

-- ── Stock guacadmin account ────────────────────────────────────────────────
-- Guacamole's schema ships a `guacadmin` user with the DOCUMENTED default
-- password and full ADMINISTER. On this instance it had never been used — every
-- login and every connection session belonged to `demo` — but it sat enabled
-- with the default credential until 2026-08-02, fronting a service that is
-- reachable (via the edge) from the internet. ufw restricting :8080 to the edge
-- and Authentik's forward-auth were the only things in front of it.
--
-- Nothing needs it: connections are managed by this file, and access is header
-- auth as `demo`. Disable it AND randomise the password, so simply re-enabling
-- the account cannot restore a credential that is public knowledge.
--
-- ⚠️ Verifying it is NOT the default is easy to get wrong. Guacamole hashes
--    password + UPPER(hex(salt)), NOT password + salt. The raw-salt form returns
--    "not default" for an account that IS default:
--      select u.password_hash = sha256(convert_to(
--               'guacadmin' || upper(encode(u.password_salt,'hex')),'UTF8'))
--        from guacamole_user u join guacamole_entity e using(entity_id)
--       where e.name = 'guacadmin';
UPDATE guacamole_user u
   SET disabled      = true,
       password_hash = sha256(convert_to(gen_random_uuid()::text,'UTF8')),
       password_salt = decode(md5(gen_random_uuid()::text),'hex'),
       password_date = now()
  FROM guacamole_entity e
 WHERE e.entity_id = u.entity_id
   AND e.name = 'guacadmin';
