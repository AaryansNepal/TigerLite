-- TigerLite v2 — auto-provision a tenant on signup.
--
-- When a new user is created via Supabase Auth, this trigger creates a default
-- tenant for them and adds an owner membership. The user can later create more
-- tenants or be invited into others.

BEGIN;

CREATE OR REPLACE FUNCTION handle_new_user() RETURNS TRIGGER
SECURITY DEFINER SET search_path = public
LANGUAGE plpgsql AS $$
DECLARE
  new_tenant_id UUID;
  base_slug TEXT;
  unique_slug TEXT;
  attempt INT := 0;
  ingest_token TEXT;
BEGIN
  -- Generate a slug from the email local-part, fall back to "tenant".
  base_slug := lower(regexp_replace(
    coalesce(split_part(NEW.email, '@', 1), 'tenant'),
    '[^a-z0-9-]', '-', 'g'
  ));
  IF base_slug = '' OR base_slug IS NULL THEN
    base_slug := 'tenant';
  END IF;

  unique_slug := base_slug;
  WHILE EXISTS (SELECT 1 FROM tenants WHERE slug = unique_slug) LOOP
    attempt := attempt + 1;
    unique_slug := base_slug || '-' || attempt::text;
  END LOOP;

  -- Generate a placeholder ingest token hash. The real token is created on
  -- demand by the control plane the first time the user opens the Telemetry
  -- connect modal.
  ingest_token := encode(gen_random_bytes(32), 'hex');

  INSERT INTO tenants (name, slug, ingest_token_hash)
  VALUES (
    coalesce(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
    unique_slug,
    crypt(ingest_token, gen_salt('bf'))
  )
  RETURNING id INTO new_tenant_id;

  INSERT INTO memberships (user_id, tenant_id, role)
  VALUES (NEW.id, new_tenant_id, 'owner');

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

COMMIT;
