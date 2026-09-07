Component({
  properties: {
    monochrome: { type: Boolean, value: false },
    title: { type: String, value: "" },
    showBack: { type: Boolean, value: false },
    backLeft: { type: Boolean, value: false },
  },
  methods: {
    goBack() {
      this.triggerEvent("back");
    },
  },
});
