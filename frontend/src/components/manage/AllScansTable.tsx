import { useMemo } from 'react'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { ScanOut } from '~/types'

// Scan timestamps are Unix seconds; render in the viewer's locale. A null
// ``ended_at`` means the scan never completed.
function formatTs(seconds: number | null): string {
  if (seconds == null) return '—'
  return new Date(seconds * 1000).toLocaleString()
}

const count = (v: number | null) => (v == null ? '—' : v.toLocaleString())

export function AllScansTable({ rows }: { rows: ScanOut[] }) {
  const columns = useMemo<MRT_ColumnDef<ScanOut>[]>(
    () => [
      {
        accessorKey: 'started_at',
        header: 'Started',
        Cell: ({ cell }) => formatTs(cell.getValue<number>()),
      },
      {
        accessorKey: 'ended_at',
        header: 'Ended',
        Cell: ({ cell }) => formatTs(cell.getValue<number | null>()),
      },
      {
        accessorKey: 'status',
        header: 'Status',
      },
      {
        accessorKey: 'samples_upserted',
        header: 'Updated or inserted',
        size: 160,
        Cell: ({ cell }) => count(cell.getValue<number | null>()),
      },
      {
        accessorKey: 'samples_skipped',
        header: 'Skipped',
        size: 120,
        Cell: ({ cell }) => count(cell.getValue<number | null>()),
      },
      {
        accessorKey: 'samples_failed',
        header: 'Failed',
        size: 120,
        Cell: ({ cell }) => count(cell.getValue<number | null>()),
      },
    ],
    [],
  )

  const table = useMaterialReactTable<ScanOut>({
    columns,
    data: rows,
    getRowId: (r) => r.scan_run_id,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enablePagination: false,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableSorting: true,
    // Most recent scan first.
    initialState: {
      density: 'comfortable',
      sorting: [{ id: 'started_at', desc: true }],
    },
    muiTablePaperProps: { elevation: 0, sx: { borderRadius: 0 } },
    localization: { noRecordsToDisplay: 'No scans recorded yet.' },
  })

  return <MaterialReactTable table={table} />
}
