import { createFileRoute } from '@tanstack/react-router'
import { Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AllScansTable } from '~/components/manage/AllScansTable'
import { scansQueryOptions, useScansQuery } from '~/utils/queryOptions'

export const Route = createFileRoute('/manage/all-scans')({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(scansQueryOptions),
  component: AllScansRoute,
})

function AllScansRoute() {
  const { data: scans } = useScansQuery()

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit">
          Manage
        </CustomLink>
        <Typography color="text.primary">All file system scans</Typography>
      </Breadcrumbs>

      <Typography variant="h5" component="h1">
        All file system scans
      </Typography>

      <AllScansTable rows={scans} />
    </Stack>
  )
}
