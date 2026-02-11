import tkinter as tk
from tkinter import ttk
import queue
import datetime
from pathlib import Path
import can
import cantools
from cantools.database.can import Database
import math, random, time
from signal_help import describe_signal
from tkinter import messagebox

# Matplotlib for plotting
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import sv_ttk


THEME = {
    "dark":  {"tile_bg": "#505050", "tile_fg": "white", "pack_bg": "#2b2b2b", "pack_fg": "white", "plot_bg": "#111111", "spine": "#444444"},
    "light": {"tile_bg": "#e6e6e6", "tile_fg": "black", "pack_bg": "#f0f0f0", "pack_fg": "black", "plot_bg": "white",  "spine": "#999999"},
}


def apply_theme(root, theme: str):
    sv_ttk.set_theme(theme)


def interpolate_color(value: float, min_val: float, max_val: float, start_hex: str, end_hex: str) -> str:
    """Interpolates a color based on a value within a range."""
    if value is None:
        return "#808080"
    value = max(min_val, min(value, max_val))

    s_r, s_g, s_b = int(start_hex[1:3], 16), int(start_hex[3:5], 16), int(start_hex[5:7], 16)
    e_r, e_g, e_b = int(end_hex[1:3], 16), int(end_hex[3:5], 16), int(end_hex[5:7], 16)

    ratio = (value - min_val) / (max_val - min_val)

    n_r = int(s_r + ratio * (e_r - s_r))
    n_g = int(s_g + ratio * (e_g - s_g))
    n_b = int(s_b + ratio * (e_b - s_b))

    return f"#{n_r:02x}{n_g:02x}{n_b:02x}"


class CANListener(can.Listener):
    """A can.Listener that puts received messages into a queue."""
    def __init__(self, msg_queue: queue.Queue):
        self.queue = msg_queue

    def on_message_received(self, msg: can.Message):
        self.queue.put(msg)

    def on_error(self, exc: Exception):
        print(f"An error occurred in the CAN listener: {exc}")


class SegmentWidget(ttk.Frame):
    """A widget representing a single BMS segment."""
    def __init__(self, parent, seg_id: int, select_callback, plot_callback):
        super().__init__(parent, borderwidth=1, relief="solid")
        self.seg_id = seg_id

        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tile = dict(bg="#505050", fg="white", font=("Consolas", 9))

        self.voltage_label = tk.Label(self, anchor="center", **tile)
        self.temp_label = tk.Label(self, anchor="center", **tile)
        self.fault_label = tk.Label(self, anchor="center", text="FT", **tile)
        self.commsFault_label = tk.Label(self, anchor="center", text="CF", **tile)

        self.voltage_label.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=1)
        self.temp_label.grid(row=1, column=0, sticky="nsew", padx=(0, 1))
        self.fault_label.grid(row=1, column=1, sticky="nsew", padx=(0, 1))
        self.commsFault_label.grid(row=1, column=2, sticky="nsew")

        voltage_signal = f"SEG_{self.seg_id}_IC_Voltage"
        temp_signal = f"SEG_{self.seg_id}_IC_Temp"
        fault_signal = f"SEG_{self.seg_id}_isFaultDetected"
        comms_fault_signal = f"SEG_{self.seg_id}_isCommsError"

        self.voltage_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(voltage_signal))
        self.temp_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(temp_signal))
        self.fault_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(fault_signal))
        self.commsFault_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(comms_fault_signal))

        self.voltage_label.bind("<Button-1>", lambda e: [select_callback(self.seg_id), plot_callback(voltage_signal)])
        self.temp_label.bind("<Button-1>", lambda e: [select_callback(self.seg_id), plot_callback(temp_signal)])
        self.fault_label.bind("<Button-1>", lambda e: [select_callback(self.seg_id), plot_callback(fault_signal)])
        self.commsFault_label.bind("<Button-1>", lambda e: [select_callback(self.seg_id), plot_callback(comms_fault_signal)])

    def update_data(self, voltage: float, temp: float, is_faulted: bool, is_comms_fault: bool):
        if voltage is not None:
            self.voltage_label.config(text=f"{voltage:7.3f} V")
            self.voltage_label.config(bg=interpolate_color(voltage, 48.0, 67.2, "#FF0000", "#00FF00"))

        if temp is not None:
            self.temp_label.config(text=f"{temp:6.2f} °C")
            self.temp_label.config(bg=interpolate_color(temp, 10, 100, "#00FF00", "#FF0000"))

        app = self.winfo_toplevel()
        t = THEME[app.theme]

        self.fault_label.config(bg="#FF0000" if is_faulted else t["tile_bg"], fg=t["tile_fg"])
        self.commsFault_label.config(bg="#FFA500" if is_comms_fault else t["tile_bg"], fg=t["tile_fg"])


class CellWidget(ttk.Frame):
    """A widget representing a single BMS cell."""
    def __init__(self, parent, cell_id: tuple, select_callback, plot_callback):
        super().__init__(parent, borderwidth=1, relief="solid")
        self.cell_id = cell_id  # (row, col)

        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tile = dict(bg="#505050", fg="white", font=("Consolas", 9))

        self.voltage_label = tk.Label(self, anchor="center", **tile)
        self.voltageDiff_label = tk.Label(self, anchor="center", **tile)
        self.temp_label = tk.Label(self, anchor="center", **tile)
        self.fault_label = tk.Label(self, anchor="center", text="FT", **tile)
        self.discharging_label = tk.Label(self, anchor="center", text="DC", **tile)

        self.voltage_label.grid(row=0, column=0, sticky="nsew", pady=1, padx=(0, 1))
        self.voltageDiff_label.grid(row=0, column=1, columnspan=2, sticky="nsew", pady=1)
        self.temp_label.grid(row=1, column=0, sticky="nsew", padx=(0, 1))
        self.fault_label.grid(row=1, column=1, sticky="nsew", padx=(0, 1))
        self.discharging_label.grid(row=1, column=2, sticky="nsew")

        row, col = self.cell_id
        seg = col + 1
        cell_idx = row + 1

        voltage_signal = f"CELL_{seg}x{cell_idx}_Voltage"
        diff_signal = f"CELL_{seg}x{cell_idx}_VoltageDiff"
        temp_signal = f"CELL_{seg}x{cell_idx}_Temp"
        fault_signal = f"CELL_{seg}x{cell_idx}_isFaultDetected"
        discharge_signal = f"CELL_{seg}x{cell_idx}_isDischarging"

        self.voltage_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(voltage_signal))
        self.voltageDiff_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(diff_signal))
        self.temp_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(temp_signal))
        self.fault_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(fault_signal))
        self.discharging_label.bind("<Button-3>", lambda e: self.winfo_toplevel().show_signal_info(discharge_signal))

        self.voltage_label.bind("<Button-1>", lambda e: [select_callback(self.cell_id), plot_callback(voltage_signal)])
        self.voltageDiff_label.bind("<Button-1>", lambda e: [select_callback(self.cell_id), plot_callback(diff_signal)])
        self.temp_label.bind("<Button-1>", lambda e: [select_callback(self.cell_id), plot_callback(temp_signal)])
        self.fault_label.bind("<Button-1>", lambda e: [select_callback(self.cell_id), plot_callback(fault_signal)])
        self.discharging_label.bind("<Button-1>", lambda e: [select_callback(self.cell_id), plot_callback(discharge_signal)])

    def update_data(self, voltage: float, voltageDiff: int, temp: float, is_faulted: bool, is_discharging: bool):
        if voltage is not None:
            self.voltage_label.config(text=f"{voltage:5.3f} V")
            self.voltage_label.config(bg=interpolate_color(voltage, 3.0, 4.2, "#FF0000", "#00FF00"))

        if voltageDiff is not None:
            self.voltageDiff_label.config(text=f"{int(voltageDiff):+4d} mV")
            self.voltageDiff_label.config(bg=interpolate_color(abs(int(voltageDiff)), 0, 500, "#00FF00", "#FF0000"))

        if temp is not None:
            self.temp_label.config(text=f"{temp:6.2f} °C")
            self.temp_label.config(bg=interpolate_color(temp, 10, 100, "#00FF00", "#FF0000"))

        app = self.winfo_toplevel()
        t = THEME[app.theme]

        self.fault_label.config(bg="#FF0000" if is_faulted else t["tile_bg"], fg=t["tile_fg"])
        self.discharging_label.config(bg="#0000FF" if is_discharging else t["tile_bg"], fg=t["tile_fg"])


class SystemInfoFrame(ttk.Frame):
    def __init__(self, parent, plot_callback):
        super().__init__(parent, borderwidth=1, relief="solid", padding=10)

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Voltage:", font=("Helvetica", 32), anchor="w").grid(row=0, column=0, sticky="nsew", padx=5, pady=3)
        ttk.Label(self, text="Current:", font=("Helvetica", 32), anchor="w").grid(row=1, column=0, sticky="nsew", padx=5)

        self.voltage_value_label = tk.Label(self, text="--- V", font=("Segoe UI", 32), cursor="hand2",
                                            bg="#2b2b2b", fg="white", anchor="center")
        self.voltage_value_label.grid(row=0, column=1, sticky="nsew", pady=3)

        self.current_value_label = tk.Label(self, text="--- A", font=("Segoe UI", 32), cursor="hand2",
                                            bg="#2b2b2b", fg="white", anchor="center")
        self.current_value_label.grid(row=1, column=1, sticky="nsew")

        self.voltage_value_label.bind("<Button-1>", lambda e: plot_callback("BMS_Pack_Voltage"))
        self.current_value_label.bind("<Button-1>", lambda e: plot_callback("BMS_Pack_Current"))

    def update_values(self, voltage, current):
        self.voltage_value_label.config(text=f"{voltage:.2f} V" if voltage is not None else "--- V")
        self.current_value_label.config(text=f"{current:.2f} A" if current is not None else "--- A")


class LogFrame(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="Other CAN Data", padding=5)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(self)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        v_scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        h_scrollbar = ttk.Scrollbar(list_frame, orient="horizontal")

        self.text_list = tk.Listbox(list_frame, yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set,
                                    font=("Courier New", 8))
        v_scrollbar.config(command=self.text_list.yview)
        h_scrollbar.config(command=self.text_list.xview)

        self.text_list.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        self.log_order = []

    def log_message(self, msg_content: str, can_id: int):
        timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        header = f"{timestamp} | ID: {can_id:<#05x}"
        log_entry = f"{header} | {msg_content}"

        if can_id in self.log_order:
            try:
                index = self.log_order.index(can_id)
                self.text_list.delete(index)
                self.text_list.insert(index, log_entry)
            except ValueError:
                self._add_new_log_entry(log_entry, can_id)
        else:
            self._add_new_log_entry(log_entry, can_id)

    def _add_new_log_entry(self, log_entry: str, can_id: int):
        if len(self.log_order) >= 500:
            self.log_order.pop(0)
            self.text_list.delete(0)

        self.log_order.append(can_id)
        self.text_list.insert(tk.END, log_entry)

        if self.text_list.yview()[1] > 0.99:
            self.text_list.yview_moveto(1.0)


class Application(tk.Tk):
    def __init__(self, usb_can_path: str, dbc_path: str, bitrate: int):
        super().__init__()
        self.title("BMS CAN Bus Monitor")
        self.geometry("1400x900")

        self.bus = None
        self.notifier = None
        self.log_writer = None
        self.log_file = None
        self.start_timestamp = 0
        self.can_message_queue = queue.Queue()
        self.db: Database = cantools.database.load_file(dbc_path)

        self.data_log = {signal.name: [] for msg in self.db.messages for signal in msg.signals}
        self.data_units = {signal.name: signal.unit for msg in self.db.messages for signal in msg.signals}
        self.signal_to_widget_map = {}

        self.segments = []
        self.cells = []
        self.selected_segment_id = 1
        self.selected_cell_id = (0, 0)
        self.plotted_signal_name = None

        self.paused = False
        self.demo_mode = True
        self.theme = "dark"

        apply_theme(self, self.theme)

        self._initialize_ui_layout()
        self._initialize_ui_components()
        self._initialize_plot()

        self.apply_custom_theme()

        if self.demo_mode:
            self.after(200, self._demo_tick)

        self._initialize_can_and_logging(usb_can_path, bitrate)

        self.after(100, self.process_can_messages)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.on_segment_selected(1)
        self.on_cell_selected((0, 0))

    def can_connected(self) -> bool:
        return self.bus is not None and self.notifier is not None

    def _is_alert_bg(self, bg: str) -> bool:
        return bg.lower() in ("#ff0000", "#ffa500", "#0000ff")

    def apply_custom_theme(self):
        t = THEME[self.theme]

        self.system_info_frame.voltage_value_label.config(bg=t["pack_bg"], fg=t["pack_fg"])
        self.system_info_frame.current_value_label.config(bg=t["pack_bg"], fg=t["pack_fg"])

        for seg in self.segments:
            if seg is None:
                continue
            for lbl in (seg.voltage_label, seg.temp_label, seg.fault_label, seg.commsFault_label):
                if not self._is_alert_bg(lbl.cget("bg")):
                    lbl.config(bg=t["tile_bg"], fg=t["tile_fg"])
                else:
                    lbl.config(fg=t["tile_fg"])

        for row in self.cells:
            for cell in row:
                if cell is None:
                    continue
                for lbl in (cell.voltage_label, cell.voltageDiff_label, cell.temp_label, cell.fault_label, cell.discharging_label):
                    if not self._is_alert_bg(lbl.cget("bg")):
                        lbl.config(bg=t["tile_bg"], fg=t["tile_fg"])
                    else:
                        lbl.config(fg=t["tile_fg"])

        self._apply_plot_theme()
        self.canvas.draw()

    def toggle_demo(self):
        if self.can_connected():
            messagebox.showinfo("Demo mode", "Demo mode is disabled while CAN is connected.")
            return

        self.demo_mode = not self.demo_mode
        self.demo_btn.config(text=f"Demo: {'ON' if self.demo_mode else 'OFF'}")
        if self.demo_mode:
            self.after(200, self._demo_tick)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.config(text="Resume" if self.paused else "Pause")

    def clear_plot(self):
        if self.plotted_signal_name and self.plotted_signal_name in self.data_log:
            self.data_log[self.plotted_signal_name].clear()
        self.update_plot()

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        apply_theme(self, self.theme)
        self.theme_btn.config(text=f"Theme: {'Dark' if self.theme == 'dark' else 'Light'}")
        self.apply_custom_theme()

    def _apply_plot_theme(self):
        t = THEME[self.theme]
        self.fig.set_facecolor(t["plot_bg"])
        self.ax.set_facecolor(t["plot_bg"])

        tick_color = "white" if self.theme == "dark" else "black"
        self.ax.tick_params(colors=tick_color)
        self.ax.xaxis.label.set_color(tick_color)
        self.ax.yaxis.label.set_color(tick_color)
        self.ax.title.set_color(tick_color)

        for spine in self.ax.spines.values():
            spine.set_color(t["spine"])

        self.ax.grid(True, linestyle="--", alpha=0.25)

    def show_signal_info(self, signal_name: str):
        unit = self.data_units.get(signal_name, "")
        messagebox.showinfo(
            "Signal info",
            f"{signal_name}\nUnit: {unit or '(none)'}\n\n{describe_signal(signal_name)}"
        )

    def _demo_tick(self):
        if self.can_connected():
            if self.demo_mode:
                self.demo_mode = False
                self.demo_btn.config(text="Demo: OFF")
            return

        if not self.demo_mode or self.paused:
            self.after(200, self._demo_tick)
            return

        now = time.time()
        if self.start_timestamp == 0:
            self.start_timestamp = now
        rt = now - self.start_timestamp

        pack_v = 320 + 10 * math.sin(rt / 5)
        pack_i = 5 * math.sin(rt / 2)

        self._demo_push("BMS_Pack_Voltage", rt, pack_v)
        self._demo_push("BMS_Pack_Current", rt, pack_i)

        for seg in range(1, 8):
            seg_v = 56 + 2 * math.sin(rt / 3 + seg)
            seg_t = 25 + 5 * math.sin(rt / 4 + seg / 2)

            self._demo_push(f"SEG_{seg}_IC_Voltage", rt, seg_v)
            self._demo_push(f"SEG_{seg}_IC_Temp", rt, seg_t)
            self._demo_push(f"SEG_{seg}_isFaultDetected", rt, 1 if random.random() < 0.002 else 0)
            self._demo_push(f"SEG_{seg}_isCommsError", rt, 1 if random.random() < 0.001 else 0)

            for cell in range(1, 17):
                v = 3.75 + 0.08 * math.sin(rt / 2 + (seg * cell) / 20) + random.uniform(-0.005, 0.005)
                vd = int((v - 3.75) * 1000)
                temp = 28 + 6 * math.sin(rt / 6 + cell / 5) + random.uniform(-0.2, 0.2)

                self._demo_push(f"CELL_{seg}x{cell}_Voltage", rt, v)
                self._demo_push(f"CELL_{seg}x{cell}_VoltageDiff", rt, vd)
                self._demo_push(f"CELL_{seg}x{cell}_Temp", rt, temp)
                self._demo_push(f"CELL_{seg}x{cell}_isDischarging", rt, 1 if random.random() < 0.02 else 0)
                self._demo_push(f"CELL_{seg}x{cell}_isFaultDetected", rt, 1 if random.random() < 0.003 else 0)

        self.after(200, self._demo_tick)

    def _demo_push(self, signal_name, rt, value):
        if signal_name in self.data_log:
            self.data_log[signal_name].append((rt, value))
            if signal_name in self.signal_to_widget_map:
                self.update_widget_for_signal(signal_name)

    def _initialize_ui_layout(self):
        # --- Top toolbar (no title) ---
        toolbar = ttk.Frame(self, padding=(0, 0))
        toolbar.pack(fill="x", pady=0)

        btn_frame = ttk.Frame(toolbar)
        btn_frame.pack(side="right", padx=10, pady=6)

        self.demo_btn = ttk.Button(btn_frame, text="Demo: ON", command=self.toggle_demo)
        self.demo_btn.pack(side="left", padx=4)

        self.pause_btn = ttk.Button(btn_frame, text="Pause", command=self.toggle_pause)
        self.pause_btn.pack(side="left", padx=4)

        self.clear_plot_btn = ttk.Button(btn_frame, text="Clear plot", command=self.clear_plot)
        self.clear_plot_btn.pack(side="left", padx=4)

        self.theme_btn = ttk.Button(btn_frame, text="Theme: Dark", command=self.toggle_theme)
        self.theme_btn.pack(side="left", padx=4)

        # --- Main content ---
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=0)
        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left_frame.columnconfigure(0, weight=1)

        # IMPORTANT: plot always gets remaining space
        left_frame.rowconfigure(0, weight=0)  # segments
        left_frame.rowconfigure(1, weight=0)  # cells (scroll area)
        left_frame.rowconfigure(2, weight=1)  # plot

        self.segment_grid_frame = ttk.Frame(left_frame)
        self.segment_grid_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))

        # --- Scrollable cell area (keeps plot visible) ---
        cell_container = ttk.Frame(left_frame)
        cell_container.grid(row=1, column=0, sticky="nsew")
        cell_container.columnconfigure(0, weight=1)
        cell_container.rowconfigure(0, weight=1)

        self.cell_canvas = tk.Canvas(cell_container, highlightthickness=0)
        self.cell_canvas.grid(row=0, column=0, sticky="nsew")

        cell_scroll = ttk.Scrollbar(cell_container, orient="vertical", command=self.cell_canvas.yview)
        cell_scroll.grid(row=0, column=1, sticky="ns")
        self.cell_canvas.configure(yscrollcommand=cell_scroll.set)

        self.cell_grid_frame = ttk.Frame(self.cell_canvas)
        self._cell_window = self.cell_canvas.create_window((0, 0), window=self.cell_grid_frame, anchor="nw")

        def _on_cell_configure(event):
            self.cell_canvas.configure(scrollregion=self.cell_canvas.bbox("all"))

        def _on_canvas_configure(event):
            # Make inner frame width track canvas width (prevents weird horizontal clipping)
            self.cell_canvas.itemconfigure(self._cell_window, width=event.width)

        self.cell_grid_frame.bind("<Configure>", _on_cell_configure)
        self.cell_canvas.bind("<Configure>", _on_canvas_configure)

        # Wheel scroll
        def _on_mousewheel(e):
            # Windows: e.delta is multiples of 120
            self.cell_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self.cell_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.plot_frame = ttk.Frame(left_frame)
        self.plot_frame.grid(row=2, column=0, sticky="nsew", pady=(6, 0))

        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=0)
        right_frame.rowconfigure(1, weight=1)

        self.system_info_frame = SystemInfoFrame(right_frame, self.on_signal_selected_for_plot)
        self.system_info_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.log_frame = LogFrame(right_frame)
        self.log_frame.grid(row=1, column=0, sticky="nsew")

    def _initialize_ui_components(self):
        num_cols = 7

        # Segments
        self.segments = [None for _ in range(num_cols)]
        for col in range(num_cols):
            self.segment_grid_frame.columnconfigure(col, weight=1)
            seg_id = col + 1
            w = SegmentWidget(self.segment_grid_frame, seg_id, self.on_segment_selected, self.on_signal_selected_for_plot)
            w.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            self.segments[col] = w

            self.signal_to_widget_map[f"SEG_{seg_id}_IC_Voltage"] = w
            self.signal_to_widget_map[f"SEG_{seg_id}_IC_Temp"] = w
            self.signal_to_widget_map[f"SEG_{seg_id}_isFaultDetected"] = w
            self.signal_to_widget_map[f"SEG_{seg_id}_isCommsError"] = w

        # Cells
        num_rows = 16
        self.cells = [[None for _ in range(num_cols)] for _ in range(num_rows)]

        for row in range(num_rows):
            self.cell_grid_frame.rowconfigure(row, weight=1)
            for col in range(num_cols):
                self.cell_grid_frame.columnconfigure(col, weight=1)

                w = CellWidget(self.cell_grid_frame, (row, col), self.on_cell_selected, self.on_signal_selected_for_plot)
                w.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
                self.cells[row][col] = w

                seg = col + 1
                cell_idx = row + 1

                self.signal_to_widget_map[f"CELL_{seg}x{cell_idx}_Voltage"] = w
                self.signal_to_widget_map[f"CELL_{seg}x{cell_idx}_VoltageDiff"] = w
                self.signal_to_widget_map[f"CELL_{seg}x{cell_idx}_Temp"] = w
                self.signal_to_widget_map[f"CELL_{seg}x{cell_idx}_isDischarging"] = w
                self.signal_to_widget_map[f"CELL_{seg}x{cell_idx}_isFaultDetected"] = w

        self.signal_to_widget_map["BMS_Pack_Voltage"] = self.system_info_frame
        self.signal_to_widget_map["BMS_Pack_Current"] = self.system_info_frame

    def _initialize_plot(self):
        self.fig = Figure(figsize=(5, 2.8), dpi=100)
        self.ax = self.fig.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.update_plot()

    def _initialize_can_and_logging(self, usb_can_path: str, bitrate: int):
        try:
            self.bus = can.Bus(interface="slcan", channel=usb_can_path, bitrate=bitrate)

            log_filename = f"can_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            log_file_path = Path("logs") / log_filename
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = open(log_file_path, "a", encoding='utf-8', newline='')
            self.log_writer = can.CanutilsLogWriter(self.log_file)

            listeners = [CANListener(self.can_message_queue), self.log_writer]
            self.notifier = can.Notifier(self.bus, listeners)
            self.log_frame.log_message("Successfully connected to CAN bus.", 0x00)

            if self.demo_mode:
                self.demo_mode = False
                self.demo_btn.config(text="Demo: OFF")

        except Exception as e:
            self.log_frame.log_message(f"Error initializing CAN: {e}", 0x00)
            self.notifier = None
            self.bus = None

    def process_can_messages(self):
        if self.paused:
            self.after(100, self.process_can_messages)
            return

        try:
            while not self.can_message_queue.empty():
                msg: can.Message = self.can_message_queue.get_nowait()

                if self.start_timestamp == 0:
                    self.start_timestamp = msg.timestamp

                relative_time = msg.timestamp - self.start_timestamp

                try:
                    decoded = self.db.decode_message(msg.arbitration_id, msg.data)
                    is_displayed_on_gui = any(s_name in self.signal_to_widget_map for s_name in decoded.keys())

                    if not is_displayed_on_gui:
                        try:
                            message_name = self.db.get_message_by_frame_id(msg.arbitration_id).name
                            log_content = f"{message_name} {decoded}"
                        except Exception:
                            log_content = f"{decoded}"
                        self.log_frame.log_message(log_content, msg.arbitration_id)

                    for signal_name, value in decoded.items():
                        if signal_name in self.data_log:
                            self.data_log[signal_name].append((relative_time, value))
                            if signal_name in self.signal_to_widget_map:
                                self.update_widget_for_signal(signal_name)

                except KeyError:
                    log_content = f"Unknown ID. Data: {' '.join(f'{b:02X}' for b in msg.data)}"
                    self.log_frame.log_message(log_content, msg.arbitration_id)

                except Exception as e:
                    print(f"Error decoding or processing message: {e}")

        finally:
            self.after(100, self.process_can_messages)

    def update_widget_for_signal(self, signal_name: str):
        widget = self.signal_to_widget_map.get(signal_name)
        if not widget:
            return

        if isinstance(widget, CellWidget):
            row, col = widget.cell_id
            seg = col + 1
            cell_idx = row + 1

            v_sig = f"CELL_{seg}x{cell_idx}_Voltage"
            vd_sig = f"CELL_{seg}x{cell_idx}_VoltageDiff"
            t_sig = f"CELL_{seg}x{cell_idx}_Temp"
            d_sig = f"CELL_{seg}x{cell_idx}_isDischarging"
            f_sig = f"CELL_{seg}x{cell_idx}_isFaultDetected"

            v = self.data_log.get(v_sig, [])[-1][1] if self.data_log.get(v_sig) else None
            vd = self.data_log.get(vd_sig, [])[-1][1] if self.data_log.get(vd_sig) else None
            t = self.data_log.get(t_sig, [])[-1][1] if self.data_log.get(t_sig) else None
            d = self.data_log.get(d_sig, [])[-1][1] if self.data_log.get(d_sig) else None
            f = self.data_log.get(f_sig, [])[-1][1] if self.data_log.get(f_sig) else None

            widget.update_data(voltage=v, voltageDiff=vd, temp=t, is_faulted=f, is_discharging=d)

        elif isinstance(widget, SegmentWidget):
            seg_id = widget.seg_id

            v_sig = f"SEG_{seg_id}_IC_Voltage"
            t_sig = f"SEG_{seg_id}_IC_Temp"
            f_sig = f"SEG_{seg_id}_isFaultDetected"
            cf_sig = f"SEG_{seg_id}_isCommsError"

            v = self.data_log.get(v_sig, [])[-1][1] if self.data_log.get(v_sig) else None
            t = self.data_log.get(t_sig, [])[-1][1] if self.data_log.get(t_sig) else None
            f = self.data_log.get(f_sig, [])[-1][1] if self.data_log.get(f_sig) else None
            cf = self.data_log.get(cf_sig, [])[-1][1] if self.data_log.get(cf_sig) else None

            widget.update_data(voltage=v, temp=t, is_faulted=f, is_comms_fault=cf)

        elif isinstance(widget, SystemInfoFrame):
            v = self.data_log.get("BMS_Pack_Voltage", [])[-1][1] if self.data_log.get("BMS_Pack_Voltage") else None
            c = self.data_log.get("BMS_Pack_Current", [])[-1][1] if self.data_log.get("BMS_Pack_Current") else None
            widget.update_values(v, c)

        if signal_name == self.plotted_signal_name:
            self.update_plot()

    def on_segment_selected(self, seg_id: int):
        col = seg_id - 1
        if self.selected_segment_id:
            old_col = self.selected_segment_id - 1
            if self.segments[old_col]:
                self.segments[old_col].config(relief="solid", borderwidth=1)

        self.selected_segment_id = seg_id
        if self.segments[col]:
            self.segments[col].config(relief="solid", borderwidth=3)

    def on_cell_selected(self, cell_id: tuple):
        if self.selected_cell_id:
            old_row, old_col = self.selected_cell_id
            if self.cells[old_row][old_col]:
                self.cells[old_row][old_col].config(relief="solid", borderwidth=1)

        self.selected_cell_id = cell_id
        new_row, new_col = cell_id
        if self.cells[new_row][new_col]:
            self.cells[new_row][new_col].config(relief="solid", borderwidth=3)

    def on_signal_selected_for_plot(self, signal_name: str):
        self.plotted_signal_name = signal_name
        self.update_plot()

    def update_plot(self):
        self.ax.cla()
        self._apply_plot_theme()

        if self.plotted_signal_name:
            signal_data = self.data_log.get(self.plotted_signal_name, [])
            signal_unit = self.data_units.get(self.plotted_signal_name, "")

            self.ax.set_title(f"{self.plotted_signal_name}")
            self.ax.set_ylabel(signal_unit if signal_unit else "Value")

            if signal_data:
                if len(signal_data) > 500:
                    signal_data = signal_data[-500:]
                times, values = zip(*signal_data)
                self.ax.plot(times, values, '.-')
        else:
            self.ax.set_title("Click a value to plot")

        self.ax.set_xlabel("Time (s)")
        self.fig.tight_layout()
        self.canvas.draw()

    def on_closing(self):
        if self.notifier:
            self.notifier.stop()
        if self.bus:
            self.bus.shutdown()
        if self.log_file:
            self.log_file.close()
        self.destroy()


def main():
    usb_can_path = "/dev/serial/by-id/usb-WeAct_Studio_USB2CANV1_ComPort_AAA120643984-if00"
    dbc_filepath = "./databases/bms_can_database.dbc"
    bitrate = 250000

    if not Path(dbc_filepath).exists():
        print(f"Error: DBC file not found at '{dbc_filepath}'")
        return

    app = Application(usb_can_path=usb_can_path, bitrate=bitrate, dbc_path=dbc_filepath)
    app.mainloop()


if __name__ == "__main__":
    main()
