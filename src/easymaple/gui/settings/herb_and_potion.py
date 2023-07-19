import tkinter as tk
from src.easymaple.gui.interfaces import LabelFrame, Frame
from src.easymaple.common.interfaces import Configurable



class HerbAndPotion(LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Herb & Potion', **kwargs)

        self.herb_and_potion_settings = HerbAndPotionSettings('herb_and_potion')
        self.is_running = tk.BooleanVar(value=self.herb_and_potion_settings.get('Is Running'))
        self.selected_option = tk.StringVar(value=self.herb_and_potion_settings.get('Selected Option'))

        run_row = Frame(self)
        run_row.pack(side=tk.TOP, fill='x', expand=True, pady=5, padx=5)
        run_button = tk.Button(
            run_row,
            textvariable=self.is_running,
            command=self._on_click_run
        )
        run_button.pack()

        option_row = Frame(self)
        option_row.pack(side=tk.TOP, fill='x', expand=True, pady=(0, 5), padx=5)
        herb_radio = tk.Radiobutton(
            option_row,
            text="Herb",
            variable=self.selected_option,
            value="Herb",
        )
        herb_radio.pack(side=tk.LEFT, padx=(0, 10))
        potion_radio = tk.Radiobutton(
            option_row,
            text="Potion",
            variable=self.selected_option,
            value="Potion",
        )
        potion_radio.pack(side=tk.LEFT, padx=(0, 10))

    def _on_click_run(self):
        if self.is_running.get():
            your_python_script_module.stop_script()
        else:
            if self.selected_option.get() == "Herb":
                your_python_script_module.run_herb_script()
            elif self.selected_option.get() == "Potion":
                your_python_script_module.run_potion_script()
        self.is_running.set(not self.is_running.get())
        self.herb_and_potion_settings.set('Is Running', self.is_running.get())
        self.herb_and_potion_settings.set('Selected Option', self.selected_option.get())
        self.herb_and_potion_settings.save_config()


class HerbAndPotionSettings(Configurable):
    DEFAULT_CONFIG = {
        'Is Running': False,
        'Selected Option': 'Herb',
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
