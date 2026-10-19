(() => {
      const root = document.getElementById('stereo-checkerboard-placement');
      const svg = root.querySelector('.placement-top');
      const ns = 'http://www.w3.org/2000/svg';
      function draw() {
        const w = Math.max(280, svg.getBoundingClientRect().width);
        const h = 250;
        const mx = w / 2;
        const my = 208;
        svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        svg.setAttribute('height', h);
        svg.replaceChildren();
        function element(tag, attributes, text) {
          const e = document.createElementNS(ns, tag);
          Object.entries(attributes).forEach(([key, value]) => e.setAttribute(key, value));
          if (text !== undefined) e.textContent = text;
          svg.appendChild(e);
          return e;
        }
        const positions = [
          { x: w * 0.16, y: 58, label: '左側／稍遠' },
          { x: mx, y: 122, label: '中央／可近' },
          { x: w * 0.84, y: 58, label: '右側／稍遠' }
        ];
        positions.forEach(p => {
          element('line', { x1: p.x, y1: p.y + 10, x2: mx, y2: my, stroke: 'var(--border)', 'stroke-width': 1, 'stroke-dasharray': '4 4' });
          const dx = mx - p.x;
          const dy = my - p.y;
          const length = Math.hypot(dx, dy);
          const tx = dy / length;
          const ty = -dx / length;
          const boardLength = Math.min(64, w * 0.18);
          for (let i = 0; i < 8; i++) {
            const a = (i / 8 - 0.5) * boardLength;
            const b = ((i + 1) / 8 - 0.5) * boardLength;
            element('line', { x1: p.x + tx * a, y1: p.y + ty * a, x2: p.x + tx * b, y2: p.y + ty * b, stroke: i % 2 ? 'var(--muted)' : 'var(--foreground)', 'stroke-width': 9 });
          }
          element('text', { x: p.x, y: p.y - 27, 'text-anchor': 'middle' }, p.label);
        });
        element('rect', { x: mx - 52, y: my - 10, width: 104, height: 28, rx: 3, fill: 'var(--muted)', stroke: 'var(--border)', 'stroke-width': 1 });
        [-24, 24].forEach(offset => {
          element('circle', { cx: mx + offset, cy: my + 3, r: 8, fill: 'var(--background)', stroke: 'var(--foreground)', 'stroke-width': 1.5 });
        });
        element('text', { x: mx, y: 242, 'text-anchor': 'middle' }, '固定雙目模組');
      }
      draw();
      new ResizeObserver(draw).observe(svg);
    })();