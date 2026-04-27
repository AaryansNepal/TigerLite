-- Fix the signup trigger: pgcrypto's functions live in the `extensions`
-- schema in Supabase (not `public`). Schema-qualify the calls and widen
-- the trigger's search_path so signup actually succeeds.

BEGIN;

CREATE OR REPLACE FUNCTION handle_new_user() RETURNS TRIGGER
SECURITY DEFINER SET search_path = public, extensions
LANGUAGE plpgsql AS $$
DECLARE
  new_tenant_id UUID;
  base_slug TEXT;
  unique_slug TEXT;
  attempt INT := 0;
  ingest_token TEXT;
BEGIN
  base_slug := lower(regexp_replace(
    coalesce(split_part(NEW.email, '@', 1), 'tenant'),
    '[^a-z0-9-]', '-', 'g'
  ));
  IF base_slug = '' OR base_slug IS NULL THEN
    base_slug := 'tenant';
  END IF;

  unique_slug := base_slug;
  WHILE EXISTS (SELECT 1 FROM public.tenants WHERE slug = unique_slug) LOOP
    attempt := attempt + 1;
    unique_slug := base_slug || '-' || attempt::text;
  END LOOP;

  -- Schema-qualify pgcrypto helpers explicitly so they resolve even if
  -- search_path drops `extensions` later.
  ingest_token := encode(extensions.gen_random_bytes(32), 'hex');

  INSERT INTO public.tenants (name, slug, ingest_token_hash)
  VALUES (
    coalesce(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
    unique_slug,
    extensions.crypt(ingest_token, extensions.gen_salt('bf'))
  )
  RETURNING id INTO new_tenant_id;

  INSERT INTO public.memberships (user_id, tenant_id, role)
  VALUES (NEW.id, new_tenant_id, 'owner');

  RETURN NEW;
END;
$$;

-- Trigger already exists from the previous migration; recreate to be safe.
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

COMMIT;
