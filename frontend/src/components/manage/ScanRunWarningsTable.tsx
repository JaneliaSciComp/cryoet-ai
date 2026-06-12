import { useMemo } from 'react'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { RunWarningOut } from '~/types'

// Run-level (no-sample) warnings: filesystem issues that aren't tied to a
// catalogued sample, e.g. an unknown subdirectory under MdSimulation/.
export function ScanRunWarningsTable({
  warnings,
}: {
  warnings: RunWarningOut[]
}) {
  const columns = useMemo<MRT_ColumnDef<RunWarningOut>[]>(
    () => [
      {
        accessorKey: 'location',
        header: 'Location',
        size: 320,
      },
      {
        accessorKey: 'message',
        header: 'Warning',
      },
    ],
    [],
  )

  const table = useMaterialReactTable({
    columns,
    data: warnings,
    getRowId: (w) => String(w.id),
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enablePagination: false,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableSorting: false,
    initialState: { density: 'comfortable' },
    muiTablePaperProps: { elevation: 0, sx: { borderRadius: 0 } },
    localization: { noRecordsToDisplay: 'No scan-level issues.' },
  })

  return <MaterialReactTable table={table} />
}
