-- Enable Supabase Realtime for the tables the dashboard subscribes to.
--
-- By default no tables are in `supabase_realtime`, so postgres_changes
-- subscriptions emit nothing. Adding them here means INSERT/UPDATE/DELETE
-- events flow to the browser, gated by the table's RLS policies.

BEGIN;

-- Use a DO block so re-running is safe (ALTER PUBLICATION ADD TABLE
-- errors if the table is already in the publication; we swallow that).
DO $$
DECLARE
  t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'public.connections',
    'public.agents',
    'public.sessions',
    'public.findings',
    'public.issues'
  ] LOOP
    BEGIN
      EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE %s', t);
    EXCEPTION WHEN duplicate_object THEN
      -- already in the publication; ignore
      NULL;
    END;
  END LOOP;
END$$;

COMMIT;
