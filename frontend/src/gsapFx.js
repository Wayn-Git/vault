import { useEffect } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

const reduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function useMotionToggler() {
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (!mq.addEventListener) return undefined
    const onChange = () => gsap.matchMedia().refresh()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
}

export function useViewEntrance(rootRef, deps = []) {
  useGSAP(
    () => {
      if (reduced()) return
      const lines = rootRef.current?.querySelectorAll('[data-enter]') ?? []
      if (!lines.length) return
      gsap.set(lines, { autoAlpha: 0, y: 14 })
      gsap.to(lines, {
        autoAlpha: 1,
        y: 0,
        duration: 0.5,
        ease: 'power3.out',
        stagger: 0.06,
        delay: 0.08,
        overwrite: 'auto',
      })
    },
    { scope: rootRef, dependencies: deps },
  )
}

export function animateCounter(el, to, duration = 0.8) {
  const from = 0
  const obj = { v: from }
  return gsap.to(obj, {
    v: to,
    duration,
    ease: 'power2.out',
    onUpdate: () => {
      el.textContent = String(Math.round(obj.v))
    },
  })
}