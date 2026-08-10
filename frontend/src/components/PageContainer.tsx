import clsx from 'clsx'

interface PageContainerProps {
  children: React.ReactNode
  className?: string
}

export default function PageContainer({ children, className }: PageContainerProps) {
  return <div className={clsx('page-container', className)}>{children}</div>
}
