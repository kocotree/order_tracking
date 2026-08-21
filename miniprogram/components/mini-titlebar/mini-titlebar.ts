Component({
  properties: {
    title: { type: String, value: "" },
    showBack: { type: Boolean, value: false },
  },
  methods: {
    goBack() {
      this.triggerEvent("back");
    },
  },
});
