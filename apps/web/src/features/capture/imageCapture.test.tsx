import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageCapture } from './imageCapture';

afterEach(() => vi.restoreAllMocks());

describe('image capture drag and drop', () => {
  it('adds a dropped image using the same selection flow as the file picker', () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const file = new File(['image'], 'notes.png', { type: 'image/png' });

    render(<ImageCapture
      title=""
      note=""
      onTitleChange={vi.fn()}
      onNoteChange={vi.fn()}
      onDraft={vi.fn()}
      onError={vi.fn()}
    />);

    const dropzone = screen.getByText('拖拽图片到这里，或点击选择').closest('label')!;
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(screen.getByAltText('待识别图片 1')).toBeInTheDocument();
    expect(screen.getByText('1 / 10 张')).toBeInTheDocument();
  });
});
