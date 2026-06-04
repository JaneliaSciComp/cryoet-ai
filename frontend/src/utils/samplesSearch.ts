import { z } from 'zod'

// Coerce single-value query params into single-element arrays so that a URL
// like `?camera=Falcon` validates against `z.array(z.string())`. TanStack
// Router's default search parser returns a string for a single occurrence and
// an array for repeated keys — handle both.
function toArray(v: unknown): unknown {
  if (v == null) return v
  return Array.isArray(v) ? v : [v]
}

// `z.coerce.boolean()` treats EVERY non-empty string as true — including
// "false" — so coerce the spellings explicitly instead. Accepts a native
// boolean (TanStack Router's default search parser JSON-decodes `true`/`false`)
// and the common string forms; anything unrecognized becomes `undefined` so
// it's dropped rather than silently read as true.
function toBoolean(v: unknown): boolean | undefined {
  if (typeof v === 'boolean') return v
  if (v === 'true' || v === '1') return true
  if (v === 'false' || v === '0') return false
  return undefined
}

const stringArray = z.preprocess(toArray, z.array(z.string()).optional())
const numberArray = z.preprocess(toArray, z.array(z.coerce.number()).optional())
const booleanish = z.preprocess(toBoolean, z.boolean().optional())

// Search-param schema for the /samples route. Lives in utils (not the route or
// the hook) so neither owner has to import the other (avoids circular deps).
export const samplesSearchSchema = z.object({
  // URL-canonical fields (§9.1)
  project: z.string().optional(),
  data_source: z.string().optional(),
  q: z.string().optional(),
  sort: z.enum(['sample_id', 'project', 'type']).optional(),
  order: z.enum(['asc', 'desc']).optional(),
  limit: z.coerce.number().int().positive().optional(),
  offset: z.coerce.number().int().nonnegative().optional(),
  // Drawer fields (extended, all optional so shared URLs round-trip)
  type: stringArray,
  microscope: stringArray,
  voltage: numberArray,
  camera: stringArray,
  image_format: stringArray,
  has_tomograms: booleanish,
  pixel_size_min: z.coerce.number().optional(),
  pixel_size_max: z.coerce.number().optional(),
  voxel_spacing_min: z.coerce.number().optional(),
  voxel_spacing_max: z.coerce.number().optional(),
  n_tilts_min: z.coerce.number().int().optional(),
  n_tilts_max: z.coerce.number().int().optional(),
})

export type SamplesSearchParams = z.infer<typeof samplesSearchSchema>

// Revised from plan §11.19: every drawer field round-trips through the URL,
// so there is no longer a "canonical subset". The previous
// SAMPLES_URL_CANONICAL_KEYS / SamplesUrlCanonicalParams exports were removed
// when the layout switched to navigating with the full filter set.

export function buildSamplesQueryString(params: SamplesSearchParams): string {
  const sp = new URLSearchParams()
  const addOne = (k: string, v: unknown) => {
    if (v === undefined || v === null || v === '') return
    sp.append(k, String(v))
  }
  const addMany = (k: string, v: unknown[] | undefined) => {
    if (!v) return
    for (const item of v) addOne(k, item)
  }
  addOne('project', params.project)
  addOne('data_source', params.data_source)
  addOne('q', params.q)
  addOne('sort', params.sort)
  addOne('order', params.order)
  addOne('limit', params.limit)
  addOne('offset', params.offset)
  addMany('type', params.type)
  addMany('microscope', params.microscope)
  addMany('voltage', params.voltage)
  addMany('camera', params.camera)
  addMany('image_format', params.image_format)
  if (params.has_tomograms !== undefined) {
    addOne('has_tomograms', params.has_tomograms)
  }
  addOne('pixel_size_min', params.pixel_size_min)
  addOne('pixel_size_max', params.pixel_size_max)
  addOne('voxel_spacing_min', params.voxel_spacing_min)
  addOne('voxel_spacing_max', params.voxel_spacing_max)
  addOne('n_tilts_min', params.n_tilts_min)
  addOne('n_tilts_max', params.n_tilts_max)
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}
