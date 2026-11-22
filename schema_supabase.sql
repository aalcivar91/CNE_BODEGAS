-- Ejecutar una sola vez en el SQL Editor de Supabase
create table if not exists public.estado_logistico (
    orden integer primary key,
    entregado integer default 0,
    fecha_hora_entrega text default '',
    usuario_entrega text default '',
    obs_entrega text default '',
    recibido_bodega integer default 0,
    fecha_hora_finalizacion text default '',
    usuario_recepcion text default '',
    obs_recepcion text default ''
);

-- Habilitar acceso desde la app (ajustar políticas RLS según seguridad requerida)
alter table public.estado_logistico enable row level security;

create policy "Lectura publica estado_logistico"
on public.estado_logistico for select
using (true);

create policy "Escritura controlada estado_logistico"
on public.estado_logistico for all
using (true)
with check (true);
