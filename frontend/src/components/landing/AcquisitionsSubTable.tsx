import { useMemo } from 'react'
import { Box, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import { sampleDetailQueryOptions } from '~/utils/queryOptions'
import type { AcquisitionOut } from '~/types'
import { CustomLink } from '~/components/CustomLink'

const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))

export function AcquisitionsSubTable({ sampleId }: { sampleId: string }) {
  const { data, isLoading, isError } = useQuery(
    sampleDetailQueryOptions(sampleId),
  )

  const columns = useMemo<MRT_ColumnDef<AcquisitionOut>[]>(
    () => [
      {
        accessorKey: 'acquisition_id',
        header: 'Acquisition',
        Cell: ({ cell }) => (
          <CustomLink
            to="/acquisitions/$acquisitionId"
            params={{ acquisitionId: cell.getValue<string>() }}
            search={{ sampleId }}
          >
            {cell.getValue<string>()}
          </CustomLink>
        ),
      },
      {
        accessorKey: 'microscope',
        header: 'Microscope',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        accessorKey: 'voltage',
        header: 'Voltage',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        accessorKey: 'camera',
        header: 'Camera',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        accessorKey: 'pixel_size',
        header: 'Pixel size',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        accessorKey: 'resolution',
        header: 'Resolution',
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        id: 'n_tilt_series',
        header: 'Tilt series',
        accessorFn: (a) => a.tilt_series.length,
        size: 100,
      },
      {
        id: 'n_tomograms',
        header: 'Tomograms',
        // Mirrors API's n_tomograms semantics: raw + post-processed combined.
        accessorFn: (a) =>
          (a.raw_tomogram ? 1 : 0) + a.post_processed_tomograms.length,
        size: 100,
      },
    ],
    [],
  )

  const table = useMaterialReactTable({
    columns,
    data: data?.acquisitions ?? [],
    getRowId: (a) => a.acquisition_id,
    state: { isLoading },
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enablePagination: false,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableSorting: false,
    initialState: { density: 'compact' },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 1 },
    },
    localization: { noRecordsToDisplay: 'No acquisitions for this sample.' },
  })

  return (
    <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
      <Typography variant="overline" color="text.secondary">
        Acquisitions
      </Typography>
      {isError ? (
        <Typography variant="body2" color="error" sx={{ mt: 1 }}>
          Failed to load acquisitions.
        </Typography>
      ) : (
        <Box sx={{ mt: 1 }}>
          <MaterialReactTable table={table} />
        </Box>
      )}
    </Box>
  )
}
