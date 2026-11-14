#[cfg(target_os = "linux")]
#[test]
fn variant_string_iteration_is_sound_in_optimized_builds() {
    use glib::variant::ToVariant;
    let variant = ["alpha", "résumé", "测试"].to_variant();
    assert_eq!(
        variant.array_iter_str().unwrap().collect::<Vec<_>>(),
        vec!["alpha", "résumé", "测试"]
    );
    assert_eq!(variant.array_iter_str().unwrap().nth(1), Some("résumé"));
    assert_eq!(variant.array_iter_str().unwrap().last(), Some("测试"));
    assert_eq!(variant.array_iter_str().unwrap().next_back(), Some("测试"));
    assert_eq!(
        variant.array_iter_str().unwrap().nth_back(1),
        Some("résumé")
    );
}
