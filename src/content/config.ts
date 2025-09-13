import { defineCollection, z } from 'astro:content';

const imageSchema = z.object({
  src: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  alt: z.string(),
  caption: z.string().optional()
});

const videoSchema = z.object({
  src: z.string(),
  poster: z.string().optional(),
  aspect: z.enum(['16:9', '4:3']).default('16:9'),
  captions: z.array(z.object({ src: z.string(), srclang: z.string(), label: z.string(), default: z.boolean().optional() })).optional()
});

const externalVideoSchema = z.object({
  kind: z.literal('youtube'),
  id: z.string(),
  title: z.string().optional(),
  aspect: z.enum(['16:9', '4:3']).default('16:9')
});

const works = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.string(),
    mediaType: z.enum(['photo', 'video', 'mixed']).default('mixed'),
    cover: imageSchema,
    images: z.array(imageSchema).default([]),
    videos: z.array(videoSchema).default([]),
    externalVideos: z.array(externalVideoSchema).default([]),
    summary: z.string().optional()
  })
});

const bio = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.string(),
  })
});

export const collections = { works, bio };
